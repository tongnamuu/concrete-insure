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
        async def chat(self,messages,**kwargs):return '{"terms":["당뇨"]}'
    request={'description':'당뇨에 관한 약관 찾아줘','cloudConsent':True}
    result=await understand_input_with_model(request,Nim())
    assert result['terms']==['당뇨'] and result['description']==request['description']
    class Bad(Nim):
        async def chat(self,messages,**kwargs):return '{"terms":["독감"]}'
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
        async def chat(self,messages,**kwargs):
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
        async def chat(self,messages,**kwargs):pytest.fail('no consent')
    text='환자: 테스트이름\n제품명: 제품에이75mg\n성분명: 오셑타미비르\n질병코드: J10.1'
    assert await prescription_candidates(text,nim=MustNotCall())==['제품에이75mg','오셑타미비르','J10.1']
    class Ungrounded:
        enabled=True
        async def chat(self,messages,**kwargs):return '{"terms":["독감"]}'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):await prescription_candidates('제품명: 타미플루',nim=Ungrounded(),consent=True)

@pytest.mark.asyncio
async def test_runtime_input_understanding_never_substitutes_literal_extraction():
    class NoCalls:
        enabled=True
        async def chat(self,messages,**kwargs):pytest.fail('missing consent')
    with pytest.raises(AppError,match='NVIDIA_KEY_REQUIRED'):
        await understand_input_with_model({'query':'독감','cloudConsent':True},None)
    with pytest.raises(AppError,match='NIM_CONSENT_REQUIRED'):
        await understand_input_with_model({'query':'독감'},NoCalls())
    class Failure:
        enabled=True
        async def chat(self,messages,**kwargs):raise AppError('NIM_TIMEOUT')
    with pytest.raises(AppError,match='NIM_TIMEOUT'):
        await understand_input_with_model({'query':'독감','cloudConsent':True},Failure())


@pytest.mark.asyncio
@pytest.mark.parametrize('description,selected',[
    ('가상 사례: 횡단보도를 걷던 보행자에게 오토바이가 부딪혔습니다.', ['횡단보도','보행자','오토바이']),
    ('가상 사례: 자전거를 타다가 미끄러졌습니다. 운전자보험 약관을 확인하고 싶어요.', ['자전거','미끄러졌','운전자보험']),
    ('가상 사례: 위층 배관 누수로 천장이 젖었습니다.', ['배관','누수','천장']),
])
async def test_nonmedical_narratives_keep_explicit_terms_and_original_statement(description, selected):
    import json
    class Nim:
        enabled=True
        async def chat(self,messages,**kwargs):
            data=json.loads(messages[-1]['content'])
            assert data=={'query':'','description':description,'confirmedTerms':[]}
            return json.dumps({'terms':selected},ensure_ascii=False)
    result=await understand_input_with_model({'description':description,'cloudConsent':True},Nim())
    assert result=={'query':'','description':description,'terms':selected}


@pytest.mark.asyncio
@pytest.mark.parametrize('invented',['운전자','골절','가해자','피해자','교통사고','운전자보험','부딪힘'])
async def test_accident_input_rejects_unstated_roles_injuries_and_normalized_terms(invented):
    import json
    class Nim:
        enabled=True
        async def chat(self,messages,**kwargs):return json.dumps({'terms':[invented]},ensure_ascii=False)
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):
        await understand_input_with_model({'description':'가상 사례: 횡단보도에서 오토바이와 부딪혔습니다.','cloudConsent':True},Nim())


@pytest.mark.asyncio
async def test_accident_verb_rewrite_fails_even_with_other_valid_terms():
    class Nim:
        enabled=True
        async def chat(self,messages,**kwargs):
            return '{"terms":["횡단보도","오토바이","부딪힘"]}'
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):
        await understand_input_with_model({'description':'가상 사례: 횡단보도에서 오토바이가 부딪혔습니다.','cloudConsent':True},Nim())
