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
        assert result['quotes']==[] and nim.calls==['chat', 'drug_complete'] and len(calls)==1
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


@pytest.mark.asyncio
async def test_salt_ingredient_connects_via_dose_source_to_verbatim_policy(tmp_path):
    """Actual NAT and PDF operations; synthetic MFDS/inference, no cloud call."""
    import pymupdf
    from concreteinsure.pdf import pdf_operation
    from concreteinsure.providers import Drugs
    from tests.mfds_fixture import row, response, xml
    record = row(name='타미플루 시험 제품') | {
        'MAIN_ITEM_INGR': '[TEST]인산 오셀타미비르', 'PN_DOC_DATA': '', 'NB_DOC_DATA': '',
        'UD_DOC_DATA': xml('오셀타미비르로서 75 mg을 투여한다.'),
        'EE_DOC_DATA': '<DOC><SECTION><ARTICLE title="1. 인플루엔자 B 바이러스 감염증"/></SECTION></DOC>'}
    drugs = Drugs(env={'MFDS_API_KEY':'test'}, transport=httpx.MockTransport(lambda _: response([record])))
    pdf, index = tmp_path/'policy.pdf', tmp_path/'policy.json.gz'
    with pymupdf.open() as doc:
        page = doc.new_page()
        lines = ['6-36 독감(인플루엔자) 특별약관', '제1조 (보험금의 지급사유)',
                 '독감 치료 목적으로 처방받으면 보험금을 지급합니다.',
                 '제2조 (독감(인플루엔자)의 정의 및 진단확정)', '오셀타미비르(oseltamivir) 성분 안내']
        for i, line in enumerate(lines): page.insert_text((40,60+i*45), line, fontname='korea')
        doc.save(pdf)
    await pdf_operation({'op':'index','pdf':str(pdf),'index':str(index)})
    try:
        product = (await drugs.lookup('타미플루'))['products'][0]
        nim = DrugNim()
        result = await run_investigation(document={'pdf':str(pdf),'index':str(index),'pages':1},
            request={'query':'약품 관련 약관','cloudConsent':True}, products=[product], nim=nim, drugs=drugs)
        assert result['coverage']['status'] == 'identified'
        assert result['coverage']['scope'] == 'policy_benefit_only'
        link = result['coverage']['items'][0]['links'][0]
        assert link['kind'] == 'ingredient' and link['term'] == '오셀타미비르'
        assert all(check['status'] == 'needs_confirmation' for check in result['coverage']['items'][0]['checks'])
        assert any('오셀타미비르' in h['quote'] for h in result['quotes'])
        from tests.test_pdf_worker import w
        source = w.extract(pdf.read_bytes())
        for hit in result['quotes']: w.verify(source, hit)
        assert any(f['kind'] == 'dose_basis' for f in result['references'][0]['facts'])
        assert nim.calls.count('drug_complete') == 1
    finally: await drugs.close()
