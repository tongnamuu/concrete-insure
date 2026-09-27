import copy
import json
import httpx
import pytest
from insurelens.agents.drug_references import resolve_drug_references, verify_drug_references, reference_from_detail, paragraphs
from insurelens.agents.drug import identify_drugs
from insurelens.providers import Drugs
from insurelens.core import AppError
from tests.mfds_fixture import provider, row, response, xml, ITEM_ID


@pytest.mark.asyncio
async def test_unknown_brand_uses_live_candidate_selection_then_source_documents():
    calls=[]
    record=row(name='새시험약정')
    record.update(MAIN_ITEM_INGR='[ABC]시험성분염', EE_DOC_DATA=xml('1. 시험 감염증의 치료'), PN_DOC_DATA='')
    def handle(request):
        calls.append(request)
        return response([record])
    drugs=Drugs(env={'MFDS_API_KEY':'test'},transport=httpx.MockTransport(handle))
    try:
        pending=await resolve_drug_references(drug_names=['새시험약'],drugs=drugs)
        assert pending['requiresSelection'] and pending['references']==[]
        assert calls[0].url.params['item_name']=='새시험약'
        result=await resolve_drug_references(drug_names=['새시험약'],products=pending['products'],drugs=drugs)
        assert not result['requiresSelection']
        assert result['specificTerms']==['시험성분염']  # No unsourced salt stripping.
        ref=result['references'][0]
        assert ref['source']['type']=='mfds_label' and ref['source']['historicalApproval']=='unverified'
        assert ref['facts'][0]['quote']==record['MAIN_ITEM_INGR']
        assert verify_drug_references([ref])
        forged=copy.deepcopy(ref);forged['facts'][0]['quote']='invented'
        with pytest.raises(AppError,match='UNVERIFIED_DRUG_REFERENCE'):verify_drug_references([forged])
        with pytest.raises(AppError,match='UNVERIFIED_DRUG_REFERENCE'):verify_drug_references([json.loads(json.dumps(ref))])
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_metabolite_requires_explicit_positive_source_and_preserves_offsets():
    drugs=provider()
    try:
        detail=await drugs.detail(ITEM_ID)
        ref=reference_from_detail(detail)
        bridge=next(f for f in ref['facts'] if f['kind']=='active_metabolite')
        assert bridge['terms']==['발록사비르']
        assert bridge['quote']==paragraphs(detail['documents'][bridge['field']])[bridge['paragraph']]
        assert all(not f['terms'] for f in ref['facts'] if '예방' in f['quote'])
        for text in ['시험성분 마르복실', '이 약은 전구약물로 활성 대사물 시험성분으로 전환되지 않는다.', '이 약은 전구약물로 활성 대사물 시험성분으로 전환된다는 추정이다.']:
            detail['documents']['PN_DOC_DATA']=xml(text)
            assert not any(f['kind']=='active_metabolite' for f in reference_from_detail(detail)['facts'])
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_no_key_no_match_and_no_drug_do_not_fabricate_reference():
    assert (await resolve_drug_references())['references']==[]
    with pytest.raises(AppError,match='MFDS_KEY_REQUIRED'):await resolve_drug_references(drug_names=['새약'])
    drugs=Drugs(env={'MFDS_API_KEY':'test'},transport=httpx.MockTransport(lambda r: response([])))
    try:
        pending=await resolve_drug_references(drug_names=['새약'],drugs=drugs)
        assert pending['missingNames']==['새약'] and pending['products']==[] and pending['references']==[]
    finally:await drugs.close()


def test_document_parser_rejects_entities_and_keeps_unicode_text():
    assert paragraphs(xml('문장 그대로 & 글자', '<table><tr><td>성분</td><td>20mg</td></tr></table>'))[0]=='문장 그대로 & 글자'
    assert '20mg' in paragraphs(xml('<table><tr><td>20mg</td></tr></table>'))[0]
    for text in ['<DOC>', '<!DOCTYPE a [<!ENTITY x "test">]><DOC>&x;</DOC>']:
        with pytest.raises(AppError,match='MFDS_INVALID_DOCUMENT'):paragraphs(text)


def test_official_ingredient_salt_is_not_normalized_or_inferred():
    result=identify_drugs([{'id':'200001234','name':'약','ingredients':'오셀타미비르인산염','url':'https://nedrug.mfds.go.kr/item'}])
    assert result['terms']==['오셀타미비르인산염']
    with pytest.raises(AppError,match='UNVERIFIED_PRODUCT'):identify_drugs([{'id':'200001234','name':'약','ingredients':'성분','url':'https://nedrug.mfds.go.kr.evil.example/'}])


@pytest.mark.asyncio
async def test_detail_rejects_wrong_item_and_only_uses_ingredient_endpoint_when_needed():
    requests=[]
    def handle(request):
        requests.append(request)
        if request.url.path.endswith('McpnDtlInq08'):
            assert request.url.params['Item_seq']==ITEM_ID
            return response([{'ITEM_SEQ':ITEM_ID,'MTRAL_NM':'시험 원료'}])
        return response([row() | {'MAIN_ITEM_INGR':'','ITEM_INGR_NAME':''}])
    drugs=Drugs(env={'MFDS_API_KEY':'a%2Bb%3D'},transport=httpx.MockTransport(handle))
    try:
        d=await drugs.detail(ITEM_ID)
        assert len(requests)==2 and requests[0].url.params['serviceKey']=='a+b='
        assert reference_from_detail(d)['facts'][0]['quote']=='시험 원료'
    finally:await drugs.close()
    drugs=Drugs(env={'MFDS_API_KEY':'test'},transport=httpx.MockTransport(lambda r:response([row('999999999')])))
    try:
        with pytest.raises(AppError,match='MFDS_PRODUCT_MISMATCH'):await drugs.detail(ITEM_ID)
    finally:await drugs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('code,error',[('20','MFDS_AUTH_FAILED'),('30','MFDS_AUTH_FAILED'),('22','MFDS_RATE_LIMIT'),('99','MFDS_REQUEST_FAILED')])
async def test_api_errors_fail_closed(code,error):
    drugs=Drugs(env={'MFDS_API_KEY':'secret-not-logged'},transport=httpx.MockTransport(lambda r:response([],code=code)))
    try:
        with pytest.raises(AppError,match=error):await drugs.lookup('시험약')
    finally:await drugs.close()
