import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from insurelens.conversation import model_context, MAX_CONTEXT_CHARS
from insurelens.core import AppError
from insurelens.agents.input import understand_input_with_model
from insurelens.server import create_app
from insurelens.store import Store
from tests.nim_fixture import ConversationNim
from tests.test_server import upload, wait

pytestmark = pytest.mark.asyncio


async def test_follow_up_reaches_nat_with_grounded_history_and_sources(tmp_path):
    nim = ConversationNim()
    app = create_app(root=tmp_path, nim=nim, drugs=SimpleNamespace(enabled=False))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost', headers={'X-Local-Request':'1'}) as client:
        case = (await client.post('/api/cases')).json()['id']
        await upload(client, case)
        route = f'/api/cases/{case}'
        cid = (await client.post(route+'/conversation')).json()['id']
        async def send(query, consent=True, **extra):
            response = await client.post(route+'/investigations', json={'query':query, 'conversationId':cid, 'cloudConsent':consent, **extra})
            return await wait(client,response.json()['jobId']) if response.status_code==202 else response
        first = await send('독감 관련 내용을 찾아줘')
        assert first['state']=='completed' and first['result']['quotes']
        assert len(nim.inputs)==1 and not nim.inputs[0].get('conversation')
        denied = await send('그 경우 제외사항은?',False)
        assert denied.status_code==409 and len(nim.inputs)==1
        assert (await send('질문',conversation=[{'query':'fabricated'}])).status_code==400
        failed = await send('실패 요청')
        assert failed['state']=='failed'
        second = await send('그 경우 제외사항은?')
        assert second['state']=='completed',second
        context = nim.inputs[-1]['conversation']
        assert len(context)==1 and context[0]['query']=='독감 관련 내용을 찾아줘'
        assert context[0]['sources'][0]['quote']==first['result']['quotes'][0]['quote']
        assert second['result']['terms']==['독감','제외사항']
        assert nim.plans[-1]['conversation']==context
        assert all(q in first['result']['quotes'] for q in second['result']['quotes'])
        assert 'answer' not in second['result']
        transcript = (await client.get(route+'/conversation')).json()
        assert [t['state'] for t in transcript['turns']]==['completed','failed','completed']
        assert transcript['turns'][0]['query']==context[0]['query']
        # Records survive reopening; original pre-conversation jobs are not imported.
        persisted = Store(tmp_path)
        assert persisted.conversation(case,first['documentId'])==transcript
        persisted.close()
        other = (await client.post('/api/cases')).json()['id']
        await upload(client,other)
        cross = await client.post(f'/api/cases/{other}/investigations',json={'query':'독감','conversationId':cid,'cloudConsent':True})
        assert cross.status_code==409
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as stranger:
            assert (await stranger.get(route+'/conversation')).status_code==404
        new = (await client.post(route+'/conversation')).json()
        assert new['id']!=cid and new['turns']==[]
        assert (await send('독감')).status_code==409
        cid=new['id']
        next_job=await send('치과')
        assert next_job['state']=='completed' and not nim.inputs[-1].get('conversation')
        await upload(client,case)
        assert (await client.get(route+'/conversation')).json()=={'id':None,'turns':[]}
        assert (await send('독감')).status_code==409
        assert (await client.delete(route)).status_code==204
        assert not app.state.store.db.execute('SELECT 1 FROM conversations WHERE case_id=?',(case,)).fetchall()
        assert not app.state.store.db.execute('SELECT 1 FROM turns').fetchall()


async def test_active_turn_blocks_new_conversation_and_excludes_cancelled_turn(tmp_path):
    started=asyncio.Event()
    async def investigate(**kwargs):
        started.set()
        await asyncio.Event().wait()
    app=create_app(root=tmp_path,nim=SimpleNamespace(enabled=True),drugs=SimpleNamespace(enabled=False),investigate=investigate)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost',headers={'X-Local-Request':'1'}) as client:
        case=(await client.post('/api/cases')).json()['id'];await upload(client,case)
        route=f'/api/cases/{case}'
        cid=(await client.post(route+'/conversation')).json()['id']
        body={'query':'독감','conversationId':cid,'cloudConsent':True}
        first=await client.post(route+'/investigations',json=body);await started.wait()
        assert (await client.post(route+'/investigations',json=body)).status_code==429
        assert (await client.post(route+'/conversation')).status_code==429
        job=first.json()['jobId'];await client.post(f'/api/jobs/{job}/cancel')
        assert (await wait(client,job))['state']=='cancelled'
        assert model_context((await client.get(route+'/conversation')).json()['turns'])==[]


async def test_context_is_bounded_and_never_invents_or_joins_terms():
    turn={'query':'독감','description':'오토바이','confirmedTerms':[], 'state':'completed',
          'result':{'terms':['독감'],'quotes':[{'id':'source1','page':1,'quote':'약관의 제외사항'+'a'*1300}]}}
    context=model_context([turn]*10)
    assert len(context)==4 and len(json.dumps(context,ensure_ascii=False))<MAX_CONTEXT_CHARS
    assert context[-1]['sources'][0]['truncated']
    assert len(context[-1]['sources'][0]['quote'])==1200
    assert model_context([{**turn,'state':'failed'},{**turn,'state':'cancelled'}])==[]
    long={**turn,'query':'x'*4000,'description':'y'*4000}
    assert len(model_context([long]*10))<4
    class Nim:
        enabled=True
        term='독감'
        async def chat(self,messages,**kwargs):
            assert 'untrusted' in messages[0]['content']
            return json.dumps({'terms':[self.term]},ensure_ascii=False)
    nim=Nim();request={'query':'그 경우 제외사항은?','cloudConsent':True}
    assert (await understand_input_with_model(request,nim,conversation=context))['terms']==['독감']
    nim.term='골절'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):
        await understand_input_with_model(request,nim,conversation=context)
    nim.term='독감오토바이'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):
        await understand_input_with_model(request,nim,conversation=context)
    nim.term='독감'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):
        await understand_input_with_model(request,nim,conversation=[])
