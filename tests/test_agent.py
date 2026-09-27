import asyncio
import json
import pytest
from insurelens.agent import run_investigation
from insurelens.core import AppError
from insurelens.provider_fallback import with_provider_fallback

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
    async def chat(self,messages,model=None):return '{"terms":["독감"]}'
    async def complete(self,messages,tools):self.messages.append(list(messages));return next(self.responses)

async def run(nim=None,request=None,op=operation):
    return await run_investigation(document={'pdf':'/trusted.pdf','index':'/trusted.index'},request=request or REQUEST,products=[],nim=nim,operation=op)

@pytest.mark.asyncio
async def test_local_and_cloud_preserve_sources_without_model_answer():
    assert (await run())['quotes'][0]['quote']==HIT['quote']
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
async def test_cancellation_never_becomes_provider_fallback():
    async def cancelled(**kwargs):raise asyncio.CancelledError()
    async def badlocal(**kwargs):pytest.fail('must not recover cancellation')
    with pytest.raises(asyncio.CancelledError):await with_provider_fallback({'request':REQUEST},cancelled,badlocal)

@pytest.mark.asyncio
async def test_fallback_is_fresh_and_labelled():
    async def fail(**kwargs):raise AppError('NIM_TIMEOUT',504)
    async def local(**kwargs):
        assert not kwargs['nim'].enabled and not kwargs['request']['cloudConsent'] and not kwargs['request']['translation']
        return {'quotes':[HIT]}
    result=await with_provider_fallback({'request':{**REQUEST,'translation':True}},fail,local)
    assert result['warnings']==['NIM_TIMEOUT'] and result['mode']=='local'
    async def ungrounded(**kwargs):raise AppError('UNGROUNDED_TERM')
    with pytest.raises(AppError,match='UNGROUNDED_TERM'):await with_provider_fallback({'request':REQUEST},ungrounded,local)

@pytest.mark.asyncio
async def test_empty_source_is_unresolved_not_coverage_denial():
    async def empty(payload):return {'hits':[],'truncated':False}
    result=await run(op=empty)
    assert result['quotes']==[] and result['coverage']['status']=='unresolved'

@pytest.mark.asyncio
async def test_step_limit_and_translation_boundary():
    class Many(Nim):
        async def chat(self,messages,model=None):return json.dumps({'terms':['alpha','beta','gamma','delta','epsilon','zeta','theta','iota','kappa']})
    request={**REQUEST,'query':'alpha beta gamma delta epsilon zeta theta iota kappa'}
    plans=[call(args={'ids':[i]},ident=str(i)) for i in range(8)]
    with pytest.raises(AppError,match='AGENT_STEP_LIMIT'):await run(Many(plans),request)
    class Translated(Nim):
        async def gloss(self,terms):return [{'id':0,'original':'changed','english':'flu'}]
    with pytest.raises(AppError,match='TRANSLATION_BOUNDARY'):await run(Translated([]),{**REQUEST,'translation':True})

@pytest.mark.asyncio
async def test_fallback_does_not_reuse_or_mutate_partial_provider_facts():
    from copy import deepcopy
    payload={'document':{'pdf':'original'},'request':{**REQUEST,'confirmedTerms':['독감']},'products':[{'name':'original'}]}
    before=deepcopy(payload)
    async def primary(**kwargs):
        kwargs['request']['confirmedTerms'].append('invented')
        kwargs['document']['pdf']='mutated'
        kwargs['products'][0]['name']='mutated'
        raise AppError('NIM_INVALID_JSON')
    calls=[]
    async def local(**kwargs):
        calls.append(kwargs)
        assert kwargs['request']['confirmedTerms']==['독감']
        assert kwargs['document']['pdf']=='original' and kwargs['products'][0]['name']=='original'
        kwargs['request']['confirmedTerms'].append('local change')
        return {'quotes':[],'coverage':{'status':'unresolved'}}
    result=await with_provider_fallback(payload,primary,local)
    assert len(calls)==1 and payload==before
    assert result['mode']=='local' and result['warnings']==['NIM_INVALID_JSON']

@pytest.mark.asyncio
async def test_pending_task_cancel_cannot_start_local_recovery():
    async def task_body():
        async def primary(**kwargs):
            asyncio.current_task().cancel()
            raise AppError('NIM_TIMEOUT')
        async def local(**kwargs):pytest.fail('pending cancellation must prevent fallback')
        await with_provider_fallback({'request':REQUEST},primary,local)
    task=asyncio.create_task(task_body())
    with pytest.raises(asyncio.CancelledError):await task

@pytest.mark.asyncio
@pytest.mark.parametrize('code',['SOURCE_INTEGRITY','INVALID_SOURCE_SPAN','INVALID_COVERAGE_SOURCE','UNGROUNDED_TERM'])
async def test_evidence_failures_never_retry_locally(code):
    async def primary(**kwargs):raise AppError(code)
    async def local(**kwargs):pytest.fail('evidence failure must be surfaced')
    with pytest.raises(AppError,match=code):await with_provider_fallback({'request':REQUEST},primary,local)

@pytest.mark.asyncio
async def test_description_only_investigation_has_no_generated_diagnosis():
    result=await run(request={'description':'조카가 독감이라고 했어요.','cloudConsent':False})
    assert result['quotes']==[HIT] and result['mode']=='local'
    assert 'diagnosis' not in result and 'answer' not in result
