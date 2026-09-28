import asyncio
import json
import pytest
from concreteinsure.agent import run_investigation
from concreteinsure.core import AppError

HIT = {'id':'1:0:2','page':1,'start':0,'end':2,'sourceStart':0,'sourceEnd':5,'quote':'독감 원문','matchedText':'독감','segments':[],'documentHash':'hash','offsetEncoding':'unicode-code-points'}
REQUEST = {'query':'독감 관련 내용 찾아줘','description':'','confirmedTerms':[],'cloudConsent':True}

async def operation(payload):
    if payload['op']=='sections':
        return {'sections':[], 'truncated':False}
    return {'hits':[HIT.copy()],'truncated':False}

def call(name='search_policy',args=None,ident='call1'):
    return {'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':ident,'type':'function','function':{'name':name,'arguments':json.dumps({'ids':[0]} if args is None else args)}}]}}
STOP={'finish_reason':'stop','message':{'role':'assistant','content':'보험금을 받을 수 있습니다. fabricated'}}

class Nim:
    enabled=True
    def __init__(self,responses):self.responses=iter(responses);self.messages=[]
    async def chat(self,messages,model=None,**kwargs):return '{"terms":["독감"]}'
    async def complete(self,messages,tools):self.messages.append(list(messages));return next(self.responses)

async def run(nim=None,request=None,op=operation):
    return await run_investigation(document={'pdf':'/trusted.pdf','index':'/trusted.index'},request=request or REQUEST,products=[],nim=nim,operation=op)

@pytest.mark.asyncio
async def test_nim_preserves_sources_without_model_answer():
    nim=Nim([call(),STOP]);result=await run(nim)
    assert result['mode']=='nim-react' and result['quotes']==[HIT]
    assert 'fabricated' not in json.dumps(result)
    assert nim.messages[1][-1]['role']=='tool'
    assert json.loads(nim.messages[1][-1]['content'])['hits'][0]['quote']==HIT['quote']

@pytest.mark.asyncio
@pytest.mark.parametrize('response,code',[(STOP,'NIM_STOP_WITHOUT_SEARCH'),({'finish_reason':'length','message':{'role':'assistant'}},'NIM_INCOMPLETE_RESPONSE'),(call('shell'),'UNSUPPORTED_TOOL'),(call(args={'ids':[999]}),'UNGROUNDED_TERM'),(call(args={'ids':[True]}),'INVALID_TOOL_ARGUMENTS'),(call('read_context',{'hitId':'invented'}),'UNKNOWN_SOURCE_ID')])
async def test_invalid_plans_fail_closed(response,code):
    with pytest.raises(AppError,match=code):await run(Nim([response]))

@pytest.mark.asyncio
async def test_repeat_refused_and_explicit_finish_supported():
    with pytest.raises(AppError,match='REPEATED_TOOL_CALL'):await run(Nim([call(),call(ident='call2')]))
    result=await run(Nim([call(),call('read_context',{'hitId':HIT['id']},'context'),call('finish_retrieval',{},'finish')]))
    assert result['quotes']==[HIT]


@pytest.mark.asyncio
async def test_empty_source_is_unresolved_not_coverage_denial():
    async def empty(payload):return {'hits':[],'truncated':False}
    result=await run(Nim([call(),STOP]),op=empty)
    assert result['quotes']==[] and result['coverage']['status']=='unresolved'

@pytest.mark.asyncio
async def test_step_limit():
    class Many(Nim):
        async def chat(self,messages,model=None,**kwargs):return json.dumps({'terms':['alpha','beta','gamma','delta','epsilon','zeta','theta','iota','kappa']})
    request={**REQUEST,'query':'alpha beta gamma delta epsilon zeta theta iota kappa'}
    plans=[call(args={'ids':[i]},ident=str(i)) for i in range(8)]
    with pytest.raises(AppError,match='AGENT_STEP_LIMIT'):await run(Many(plans),request)


@pytest.mark.asyncio
async def test_description_only_investigation_has_no_generated_diagnosis():
    result=await run(Nim([call(),STOP]),request={'description':'조카가 독감이라고 했어요.','cloudConsent':True})
    assert result['quotes']==[HIT] and result['mode']=='nim-react'
    assert 'diagnosis' not in result and 'answer' not in result

@pytest.mark.asyncio
@pytest.mark.parametrize('nim,case_input,code',[(None,REQUEST,'NVIDIA_KEY_REQUIRED'),(Nim([]),{**REQUEST,'cloudConsent':False},'NIM_CONSENT_REQUIRED'),(Nim([]),{'query':'독감'},'NIM_CONSENT_REQUIRED')])
async def test_provider_and_explicit_consent_required_before_any_work(nim,case_input,code):
    async def no_pdf(payload):pytest.fail('must not search without provider and consent')
    def no_event(*args):pytest.fail('must not begin work without provider and consent')
    with pytest.raises(AppError,match=code):
        await run_investigation(document={},request=case_input,nim=nim,operation=no_pdf,emit=no_event)

@pytest.mark.asyncio
@pytest.mark.parametrize('code',['NIM_TIMEOUT','NIM_AUTH_FAILED','NIM_MODEL_UNAVAILABLE','NIM_INVALID_JSON','UNGROUNDED_TERM'])
async def test_input_provider_failures_propagate_without_local_execution(code):
    class Failing(Nim):
        async def chat(self,messages,model=None,**kwargs):raise AppError(code)
    async def no_pdf(payload):pytest.fail('must not start a local substitute')
    with pytest.raises(AppError,match=code):await run(Failing([]),op=no_pdf)

@pytest.mark.asyncio
async def test_react_failure_does_not_repeat_search_or_return_partial_result():
    class Failing(Nim):
        async def complete(self,messages,tools):
            if not self.messages:
                self.messages.append(messages)
                return call()
            raise AppError('NIM_TIMEOUT')
    operations=[]
    async def counted(payload):
        operations.append(payload['op'])
        return await operation(payload)
    with pytest.raises(AppError,match='NIM_TIMEOUT'):await run(Failing([]),op=counted)
    assert operations==['search']

@pytest.mark.asyncio
async def test_task_cancellation_propagates_without_search():
    class Cancelled(Nim):
        async def chat(self,messages,model=None,**kwargs):raise asyncio.CancelledError()
    async def no_pdf(payload):pytest.fail('cancelled task must stop')
    with pytest.raises(asyncio.CancelledError):await run(Cancelled([]),op=no_pdf)


@pytest.mark.asyncio
async def test_accident_description_without_medical_data_uses_nat_and_real_pdf(tmp_path):
    import pymupdf
    from concreteinsure.nat import configured_investigation
    from concreteinsure.pdf import pdf_operation
    from tests.nim_fixture import ScriptedNim
    description='가상 사례: 주차장에서 승합차가 기둥에 부딪혔습니다.'
    class AccidentNim(ScriptedNim):
        async def chat(self,messages,**kwargs):
            assert json.loads(messages[-1]['content'])['description']==description
            return json.dumps({'terms':['주차장','승합차']},ensure_ascii=False)
    pdf,index=tmp_path/'policy.pdf',tmp_path/'index.json.gz'
    original='테스트용 가상 약관: 주차장에서 승합차와 충돌한 경우의 조건입니다.'
    document=pymupdf.open()
    document.new_page().insert_text((50,70),original,fontname='korea',fontsize=10)
    document.save(pdf)
    document.close()
    await pdf_operation({'op':'index','pdf':str(pdf),'index':str(index)})
    nim=AccidentNim()
    result=await configured_investigation(document={'pdf':str(pdf),'index':str(index),'pages':1},request={'description':description,'cloudConsent':True},nim=nim)
    assert result['mode']=='nim-react' and result['terms']==['주차장','승합차']
    assert result['quotes'] and result['references']==[] and result['mappings']==[]
    assert all(hit['quote']==original+'\n' for hit in result['quotes'])
    assert all(hit['segments'] for hit in result['quotes'])
    assert result['coverage']['status']=='unresolved'  # A match alone proves no payable benefit.
    assert 'answer' not in result and 'diagnosis' not in result
    assert nim.calls.count('complete')>=2
    annotated=tmp_path/'annotated.pdf'
    await pdf_operation({'op':'annotate','pdf':str(pdf),'index':str(index),'hits':result['quotes'],'output':str(annotated)})
    with pymupdf.open(annotated) as marked:
        assert all(annotation.info['content']==original+'\n' for annotation in marked[0].annots())
        assert len(list(marked[0].annots()))>0
