import copy
import json
import httpx
import pytest
from concreteinsure.agents.drug_references import verify_drug_references, reference_from_detail, paragraphs
from concreteinsure.agents.drug import identify_drugs
from concreteinsure.providers import Drugs
from concreteinsure.core import AppError
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
        pending=await drugs.lookup('새시험약')
        assert pending['requiresSelection']
        assert calls[0].url.params['item_name']=='새시험약'
        ref=reference_from_detail(await drugs.detail(pending['products'][0]['id']))
        assert ref['facts'][0]['terms']==['시험성분염']  # No unsourced salt stripping.
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
    drugs=Drugs(env={})
    try:
        with pytest.raises(AppError,match='MFDS_KEY_REQUIRED'):await drugs.lookup('새약')
    finally:await drugs.close()
    drugs=Drugs(env={'MFDS_API_KEY':'test'},transport=httpx.MockTransport(lambda r: response([])))
    try:
        pending=await drugs.lookup('새약')
        assert pending['products']==[]
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


def dose_detail(text='오셀타미비르로서 75 mg을 투여한다.', ingredient='인산 오셀타미비르'):
    return {'product': {'id': ITEM_ID, 'name': '시험캡슐', 'url': 'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq='+ITEM_ID},
            'documents': {'MAIN_ITEM_INGR': ingredient, 'UD_DOC_DATA': xml(text)}, 'retrievedAt': '2026-01-01T00:00:00Z'}


def test_dose_basis_is_literal_source_relation_not_salt_normalization():
    import hashlib
    detail = dose_detail()
    ref = reference_from_detail(detail)
    basis = next(f for f in ref['facts'] if f['kind'] == 'dose_basis')
    assert basis['terms'] == ['오셀타미비르']
    assert basis['quote'] == paragraphs(detail['documents']['UD_DOC_DATA'])[basis['paragraph']]
    assert basis['sourcePath'] == '/DOC/SECTION[1]/PARAGRAPH[1]'
    assert basis['documentHash'] == hashlib.sha256(detail['documents']['UD_DOC_DATA'].encode()).hexdigest()
    assert ref['facts'][0]['terms'] == ['인산 오셀타미비르']
    assert not any(f['kind'] == 'dose_basis' for f in reference_from_detail(detail, include_label=False)['facts'])
    assert verify_drug_references([ref])
    # Same extraction applies to another source term, without a brand dictionary.
    other = reference_from_detail(dose_detail('시험성분으로서 10 mg을 투여한다.', '시험성분염'))
    assert other['facts'][1]['terms'] == ['시험성분']


@pytest.mark.parametrize('text', [
    '오셀타미비르',  # Occurrence alone does not establish the relation.
    '오셀타미비르로서 75 mg을 투여하지 않는다.',
    '오셀타미비르로서 75 mg으로 추정한다.',
    '다른 약인 오셀타미비르로서 75 mg을 병용한다.',
    '다른성분으로서 75 mg을 투여한다.',  # Not in this product's ingredient.
    '오셀타미비르로서 75 정도를 투여한다.',  # No supported dose unit.
])
def test_unsupported_dose_relation_remains_unresolved(text):
    assert not any(f['kind'] == 'dose_basis' for f in reference_from_detail(dose_detail(text))['facts'])


def test_attribute_only_indications_retain_source_path_and_prevention_has_no_terms():
    from concreteinsure.agents.drug_references import document_fragments
    source = '<DOC title="효능효과"><SECTION title=""><ARTICLE title="1. 소아(일부 연령에는 적용되지 않는다) 및 성인의 인플루엔자 A 및 인플루엔자 B 바이러스 감염증"/><ARTICLE title="2. 인플루엔자 바이러스 감염증의 예방"/></SECTION></DOC>'
    fragments = document_fragments(source)
    assert [f['path'] for f in fragments] == ['/DOC/SECTION[1]/ARTICLE[1]/@title', '/DOC/SECTION[1]/ARTICLE[2]/@title']
    detail = dose_detail(); detail['documents']['EE_DOC_DATA'] = source
    facts = [f for f in reference_from_detail(detail)['facts'] if f['field'] == 'EE_DOC_DATA']
    assert facts[0]['terms'] == ['인플루엔자'] and facts[1]['terms'] == []
    for fact, fragment in zip(facts, fragments):
        assert fact['quote'] == fragment['text'] and fact['sourcePath'] == fragment['path']
    assert document_fragments('<DOC><SECTION title="치료"><ARTICLE title="원문 &amp; 제목"><PARAGRAPH>본문</PARAGRAPH></ARTICLE></SECTION></DOC>') == [
        {'text': '치료', 'path': '/DOC/SECTION[1]/@title'},
        {'text': '원문 & 제목', 'path': '/DOC/SECTION[1]/ARTICLE[1]/@title'},
        {'text': '본문', 'path': '/DOC/SECTION[1]/ARTICLE[1]/PARAGRAPH[1]'}]
