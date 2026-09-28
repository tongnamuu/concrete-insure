import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from concreteinsure.core import AppError
from concreteinsure.server import create_app
from tests.mfds_fixture import DrugNim, provider, ITEM_ID
from tests.test_server import fixture_pdf, wait


@asynccontextmanager
async def session(root, *, nim=None, cookies=None):
    calls=[];drugs=provider(calls);nim=nim or DrugNim()
    app=create_app(root=root,nim=nim,drugs=drugs)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
        base_url='http://localhost',headers={'X-Local-Request':'1'},cookies=cookies) as client:
        yield app,client,nim,calls


async def pending(client, *, query='조플루자를 처방받았어요', prior=False):
    case=(await client.post('/api/cases')).json()['id'];route=f'/api/cases/{case}'
    job=await client.post(route+'/documents',files={'file':('test.pdf',fixture_pdf('발록사비르 원문'),'application/pdf')})
    assert (await wait(client,job.json()['jobId']))['state']=='completed'
    cid=(await client.post(route+'/conversation')).json()['id']
    if prior:
        first=await client.post(route+'/investigations',json={'query':'독감 조항을 찾아줘','cloudConsent':True,'conversationId':cid})
        assert (await wait(client,first.json()['jobId']))['state']=='completed'
    response=await client.post(route+'/investigations',json={'query':query,'cloudConsent':True,'conversationId':cid})
    job=await wait(client,response.json()['jobId'])
    assert job['result']['requiresDrugSelection']
    return route,job


def body(**kwargs):return {'drugIds':[ITEM_ID],'cloudConsent':True,**kwargs}


async def resume(client,job,**kwargs):return await client.post(f"/api/jobs/{job['id']}/resume",json=body(**kwargs))


@pytest.mark.asyncio
async def test_resume_skips_input_and_lookup_and_keeps_single_turn(tmp_path):
    async with session(tmp_path) as (app,client,nim,calls):
        route,job=await pending(client)
        before=list(nim.calls)
        response=await resume(client,job)
        assert response.status_code==202,response.text
        done=await wait(client,response.json()['jobId'])
        assert done['state']=='completed',done
        assert nim.calls.count('chat')==1
        assert not any(e['data'].get('stage')=='input' for e in app.state.store.events(done['id']))
        assert before==['chat','drug_complete']
        assert len(calls)==2 and calls[-1].url.params['item_seq']==ITEM_ID
        transcript=(await client.get(route+'/conversation')).json()
        assert len(transcript['turns'])==1 and transcript['turns'][0]['query']=='조플루자를 처방받았어요'
        assert transcript['turns'][0]['jobId']==done['id']
        assert not transcript['turns'][0].get('resume')
        count=len(nim.calls)
        duplicate=await resume(client,job)
        assert duplicate.json()['jobId']==done['id'] and len(nim.calls)==count
        different=await resume(client,job,drugIds=['202012346'])
        assert different.status_code==409
        assert app.state.store.selection(job['id']) is not None
        await client.delete(route)
        assert app.state.store.selection(job['id']) is None


@pytest.mark.asyncio
async def test_resume_requires_consent_owner_candidates_and_no_client_facts(tmp_path):
    async with session(tmp_path) as (app,client,nim,calls):
        route,job=await pending(client)
        for payload,status in [(body(cloudConsent=False),409),(body(drugIds=[]),400),
                               (body(drugIds=['999999999']),409),(body(drugIds=[ITEM_ID,ITEM_ID]),400),
                               (body(query='changed'),400),(body(resume_facts={}),400)]:
            response=await client.post(f"/api/jobs/{job['id']}/resume",json=payload)
            assert response.status_code==status,response.text
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost',headers={'X-Local-Request':'1'}) as stranger:
            assert (await resume(stranger,job)).status_code==404
        assert len(calls)==1 and nim.calls.count('chat')==1
        assert len((await client.get(route+'/conversation')).json()['turns'])==1


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['conversation','document','question'])
async def test_stale_selection_cannot_resume(tmp_path,change):
    async with session(tmp_path) as (app,client,nim,calls):
        route,job=await pending(client)
        if change=='conversation':await client.post(route+'/conversation')
        elif change=='document':
            response=await client.post(route+'/documents',files={'file':('new.pdf',fixture_pdf('다른 원문'),'application/pdf')})
            await wait(client,response.json()['jobId'])
        else:
            cid=(await client.get(route+'/conversation')).json()['id']
            response=await client.post(route+'/investigations',json={'query':'독감','cloudConsent':True,'conversationId':cid})
            await wait(client,response.json()['jobId'])
        count=len(calls)
        result=await resume(client,job)
        assert result.status_code==409 and result.json()['error']=='SELECTION_EXPIRED'
        assert len(calls)==count


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy',[False,True])
async def test_pending_selection_survives_server_restart_and_legacy_migration(tmp_path,legacy):
    async with session(tmp_path) as (app,client,nim,calls):
        route,job=await pending(client);cookies=dict(client.cookies)
        if legacy:app.state.store.db.execute('DELETE FROM selection_checkpoints')
    class NoInput(DrugNim):
        async def chat(self,*args,**kwargs):pytest.fail('saved input must be restored')
    async with session(tmp_path,nim=NoInput(),cookies=cookies) as (app,client,nim,calls):
        turn=(await client.get(route+'/conversation')).json()['turns'][0]
        assert turn['resume']['jobId']==job['id']
        response=await resume(client,job)
        done=await wait(client,response.json()['jobId'])
        assert done['state']=='completed',done
        assert len(calls)==1 and calls[0].url.path.endswith('getDrugPrdtPrmsnDtlInq08')


@pytest.mark.asyncio
async def test_duplicate_request_and_cancel_retry_do_not_restart_input(tmp_path):
    entered=asyncio.Event()
    class Controlled(DrugNim):
        block=False
        async def complete(self,messages,tools):
            if self.block:
                entered.set();await asyncio.Event().wait()
            return await super().complete(messages,tools)
    nim=Controlled()
    async with session(tmp_path,nim=nim) as (app,client,nim,calls):
        route,job=await pending(client);nim.block=True
        first=await resume(client,job);await asyncio.wait_for(entered.wait(),15)
        duplicate=await resume(client,job)
        assert duplicate.json()['jobId']==first.json()['jobId']
        await client.post(f"/api/jobs/{first.json()['jobId']}/cancel")
        assert (await wait(client,first.json()['jobId']))['state']=='cancelled'
        transcript=(await client.get(route+'/conversation')).json()
        assert len(transcript['turns'])==1 and transcript['turns'][0]['resume']['selectedIds']==[ITEM_ID]
        nim.block=False
        again=await resume(client,job)
        assert again.json()['jobId']!=first.json()['jobId']
        assert (await wait(client,again.json()['jobId']))['state']=='completed'
        assert nim.calls.count('chat')==1 and len(calls)==2


@pytest.mark.asyncio
async def test_resume_revalidates_saved_search_terms(tmp_path):
    import json
    async with session(tmp_path) as (app,client,nim,calls):
        route,job=await pending(client)
        cp=app.state.store.selection(job['id'])
        cp['payload']['facts']['terms']=['fabricated']
        app.state.store.db.execute('UPDATE selection_checkpoints SET payload=? WHERE job_id=?',(json.dumps(cp['payload']),job['id']))
        response=await resume(client,job)
        assert response.status_code==400
        assert len(calls)==1


@pytest.mark.asyncio
async def test_failed_continuation_preserves_original_context_for_retry(tmp_path):
    import json
    class Controlled(DrugNim):
        fail=False
        observed=None
        async def complete(self,messages,tools):
            if self.fail:raise AppError('NIM_TIMEOUT',504)
            if not any(t['function']['name'].startswith('medicine__') for t in tools):
                self.observed=json.loads(next(m['content'] for m in messages if m['role']=='user'))
            return await super().complete(messages,tools)
    nim=Controlled()
    async with session(tmp_path,nim=nim) as (app,client,nim,calls):
        route,job=await pending(client,prior=True)
        nim.fail=True
        response=await resume(client,job)
        failed=await wait(client,response.json()['jobId'])
        assert failed['state']=='failed' and failed['error']=='NIM_TIMEOUT'
        nim.fail=False
        response=await resume(client,job)
        assert (await wait(client,response.json()['jobId']))['state']=='completed'
        assert nim.observed['query']=='조플루자를 처방받았어요'
        assert [t['query'] for t in nim.observed['conversation']]==['독감 조항을 찾아줘']
        assert len((await client.get(route+'/conversation')).json()['turns'])==2
        assert nim.calls.count('chat')==2 and len(calls)==2


@pytest.mark.asyncio
async def test_resume_requires_selection_for_each_explicit_medicine(tmp_path):
    import json
    class BothNames(DrugNim):
        async def chat(self,*args,**kwargs):
            value=json.loads(await super().chat(*args,**kwargs))
            value['drugNames']=['조플루자','타미플루']
            return json.dumps(value,ensure_ascii=False)
    async with session(tmp_path,nim=BothNames()) as (app,client,nim,calls):
        route,job=await pending(client,query='조플루자와 타미플루를 확인해줘')
        response=await resume(client,job)
        assert response.status_code==409 and response.json()['error']=='DRUG_SELECTION_INCOMPLETE'
        assert len(calls)==2 and nim.calls.count('chat')==1
