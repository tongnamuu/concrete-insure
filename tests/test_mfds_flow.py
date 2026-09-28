import json

import httpx
import pytest

from concreteinsure.nat import configured_investigation as run_investigation
from concreteinsure.agents.input import understand_input_with_model
from concreteinsure.conversation import model_context
from concreteinsure.core import AppError
from concreteinsure.server import create_app
from tests.mfds_fixture import provider, DrugNim, ITEM_ID
from tests.test_server import fixture_pdf, wait


@pytest.mark.asyncio
async def test_pending_selection_never_returns_policy_evidence_or_calls_react():
    nim=DrugNim();calls=[];drugs=provider(calls)
    async def no_pdf(_):pytest.fail('selection is required before policy retrieval')
    try:
        result=await run_investigation(document={}, request={'query':'조플루자','cloudConsent':True},nim=nim,drugs=drugs,operation=no_pdf)
        assert result['requiresDrugSelection'] and len(result['products'])==2
        assert result['quotes']==[] and nim.calls==['chat', 'drug_complete', 'drug_complete'] and len(calls)==1
        assert model_context([{'state':'completed','result':result}])==[]
        with pytest.raises(AppError,match='NIM_CONSENT_REQUIRED'):
            await run_investigation(document={},request={'query':'조플루자'},nim=nim,drugs=drugs,operation=no_pdf)
        assert len(calls)==1
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_drug_names_cannot_come_from_model_knowledge_or_policy_history():
    class Nim:
        enabled=True
        async def chat(self,*args,**kwargs):return json.dumps({'terms':['독감'],'drugNames':['새시험약']})
    history=[{'query':'독감','description':'','confirmedTerms':[],'terms':['독감'],
              'sources':[{'quote':'새시험약'}]}]
    with pytest.raises(AppError,match='UNGROUNDED_DRUG_NAME'):
        await understand_input_with_model({'query':'독감','cloudConsent':True},Nim(),conversation=history)


@pytest.mark.asyncio
async def test_http_selection_persists_case_candidates_checks_ownership_and_uses_current_details(tmp_path):
    calls=[];drugs=provider(calls);nim=DrugNim()
    app=create_app(root=tmp_path,nim=nim,drugs=drugs)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost',headers={'X-Local-Request':'1'}) as client:
        case=(await client.post('/api/cases')).json()['id'];route=f'/api/cases/{case}'
        upload=await client.post(route+'/documents',files={'file':('test.pdf',fixture_pdf('발록사비르 원문'),'application/pdf')})
        assert (await wait(client,upload.json()['jobId']))['state']=='completed'
        cid=(await client.post(route+'/conversation')).json()['id']
        body={'query':'조플루자를 처방받았어요','cloudConsent':True,'conversationId':cid}
        pending=await client.post(route+'/investigations',json=body)
        pending=await wait(client,pending.json()['jobId'])
        assert pending['result']['requiresDrugSelection']
        case_record=(await client.get(route)).json()
        assert {p['id'] for p in case_record['products']}=={ITEM_ID,'202012346'}
        assert (await client.post(route+'/investigations',json={**body,'drugIds':['999999999']})).status_code==400
        assert (await client.post(route+'/investigations',json={**body,'drugIds':[ITEM_ID],'cloudConsent':False})).status_code==409
        assert len(calls)==1
        completed=await client.post(route+'/investigations',json={**body,'drugIds':[ITEM_ID]})
        completed=await wait(client,completed.json()['jobId'])
        assert completed['state']=='completed',completed
        result=completed['result']
        assert result['references'][0]['source']['type']=='mfds_label'
        assert any('발록사비르' in h['quote'] for h in result['quotes'])
        assert len(calls)==2 and calls[-1].url.params['item_seq']==ITEM_ID
        transcript=(await client.get(route+'/conversation')).json()
        assert len(transcript['turns'])==2 and len(model_context(transcript['turns']))==1
        # Every new selected search refreshes details; no stale local catalog.
        next_job=await client.post(route+'/investigations',json={**body,'drugIds':[ITEM_ID]})
        assert (await wait(client,next_job.json()['jobId']))['state']=='completed'
        assert len(calls)==3


@pytest.mark.asyncio
async def test_mfds_timeout_remains_failure_without_local_brand_fallback():
    class Unavailable:
        enabled=True
        async def lookup(self,name):raise AppError('MFDS_TIMEOUT',504)
    async def no_pdf(_):pytest.fail('must not replace provider failure with local evidence')
    with pytest.raises(AppError,match='MFDS_TIMEOUT'):
        await run_investigation(document={},request={'query':'조플루자','cloudConsent':True},nim=DrugNim(),drugs=Unavailable(),operation=no_pdf)
