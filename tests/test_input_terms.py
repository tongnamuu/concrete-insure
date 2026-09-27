import pytest
from insurelens.agents.input import understand_input, understand_input_with_model
from insurelens.core import AppError

def test_brand_only_and_generic_retry():
    assert understand_input({'description':'조플루자를 처방받았습니다.'})['terms']==['조플루자']
    assert understand_input({'query':'다시 확인해주세요. 해당하는 사안이 있을텐데'})['terms']==[]

def test_disease_code_and_confirmed_facts_preserved():
    result=understand_input({'query':'당뇨에 관한 약관 찾아줘. J10.1','confirmedTerms':['처방']})
    assert result['terms']==['처방','당뇨','J10.1']

@pytest.mark.asyncio
async def test_model_terms_must_be_literal_and_description_remains_unmodified():
    class Nim:
        enabled=True
        async def chat(self,messages):return '{"terms":["당뇨"]}'
    request={'description':'당뇨에 관한 약관 찾아줘','cloudConsent':True}
    result=await understand_input_with_model(request,Nim())
    assert result['terms']==['당뇨'] and result['description']==request['description']
    class Bad(Nim):
        async def chat(self,messages):return '{"terms":["독감"]}'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):await understand_input_with_model({'description':'조플루자를 처방받았습니다.','cloudConsent':True},Bad())

@pytest.mark.asyncio
async def test_prescription_candidates_are_explicit_drafts_only():
    from insurelens.agents.prescription import prescription_candidates
    assert await prescription_candidates('제품명: 조플루자\n질병코드: J10.1') == ['조플루자','J10.1']
    assert await prescription_candidates('타미플루를 복용합니다.') == []

@pytest.mark.parametrize('case_input',[{}, {'query':' ','description':'\n '}, {'description':'x'*4001}, {'description':'독감','diagnosis':'verified'}])
def test_invalid_case_input_rejected_at_module_boundary(case_input):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):understand_input(case_input)

@pytest.mark.asyncio
async def test_raw_description_and_exact_confirmed_terms_reach_model_unchanged():
    description='  조카가 독감 진단을 받았고 조플루자를 처방받았어요.\n처방전은 없어요.  '
    confirmed=['처방','성분 에이','J10.1']
    class Nim:
        enabled=True
        async def chat(self,messages):
            import json
            data=json.loads(messages[-1]['content'])
            assert data['description']==description and data['confirmedTerms']==confirmed
            return '{"terms":["독감","조플루자"]}'
    result=await understand_input_with_model({'description':description,'confirmedTerms':confirmed,'cloudConsent':True},Nim())
    assert result['description']==description
    assert result['terms']==['독감','조플루자',*confirmed]
    assert confirmed==['처방','성분 에이','J10.1']

@pytest.mark.asyncio
async def test_prescription_no_consent_and_ocr_spelling_are_preserved():
    from insurelens.agents.prescription import prescription_candidates
    class MustNotCall:
        enabled=True
        async def chat(self,messages):pytest.fail('no consent')
    text='환자: 테스트이름\n제품명: 제품에이75mg\n성분명: 오셑타미비르\n질병코드: J10.1'
    assert await prescription_candidates(text,nim=MustNotCall())==['제품에이75mg','오셑타미비르','J10.1']
    class Ungrounded:
        enabled=True
        async def chat(self,messages):return '{"terms":["독감"]}'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):await prescription_candidates('제품명: 타미플루',nim=Ungrounded(),consent=True)
