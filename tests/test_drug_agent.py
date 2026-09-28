"""Real NAT built-in agent, injected inference/MFDS fixtures, no external calls."""
import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from concreteinsure.agents.drug_agent import investigate_if_needed, _state, _runner
from concreteinsure.core import AppError
from concreteinsure.diagnostics import RuntimeLog, log_context
from concreteinsure.nat import configured_investigation
from tests.mfds_fixture import DrugNim, provider


async def specialty(nim, drugs, *, names=None, products=None, consent=True, emit=lambda *_: None):
    async def investigate(**args):
        result = await investigate_if_needed(names=names or [], products=products, nim=nim, drugs=drugs,
                                             emit=emit, consent=consent)
        return {'mode': 'nim-react', 'quotes': [], 'specialist': result}
    with patch('concreteinsure.agent.run_investigation', investigate):
        return (await configured_investigation(nim=nim, request={'cloudConsent': consent}))['specialist']


@pytest.mark.asyncio
async def test_non_drug_route_skips_specialist_model_and_mfds():
    class NoNim:
        enabled=True
        async def complete(self,*args):pytest.fail('no medicine means no specialist inference')
    result=await specialty(NoNim(), SimpleNamespace(enabled=False))
    assert result['status']=='skipped' and result['references']==[]
    assert _state.get() is None and _runner.get() is None


@pytest.mark.asyncio
async def test_native_agent_inspects_sources_and_terminates_via_tool_without_generated_answer():
    calls=[];drugs=provider(calls);nim=DrugNim()
    try:
        product=(await drugs.lookup('조플루자'))['products'][0];calls.clear()
        result=await specialty(nim,drugs,products=[product])
        assert result['status']=='ready' and len(calls)==1
        assert nim.calls==['drug_complete']*2  # ingredient -> label; code decides completion
        assert result['specificTerms']==['발록사비르 마르복실','발록사비르']
        assert result['references'][0]['facts'][-1]['quote'].endswith('예방')
        assert _state.get() is None and _runner.get() is None
    finally:await drugs.close()


def tool(name, args=None, identifier='test-call'):
    return {'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[
        {'id':identifier,'type':'function','function':{'name':'medicine__'+name,'arguments':json.dumps(args or {})}}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize('response,code',[
    (tool('lookup_products',{'name_id':4}),'UNGROUNDED_DRUG_NAME'),
    (tool('lookup_products',{'name_id':True}),'INVALID_TOOL_ARGUMENTS'),
    (tool('lookup_products',{'name_id':0,'secret':'must-not-appear'}),'INVALID_TOOL_ARGUMENTS'),
    (tool('inspect_ingredients',{'product_id':0}),'UNVERIFIED_PRODUCT'),
    (tool('finish_evidence'),'UNSUPPORTED_TOOL'),
    (tool('shell'),'UNSUPPORTED_TOOL'),
    ({'finish_reason':'stop','message':{'role':'assistant','content':'invented ingredient and payout'}},'DRUG_AGENT_UNFINISHED'),
])
async def test_agent_cannot_invent_select_or_skip_evidence(response,code,caplog):
    class Nim:
        enabled=True
        async def complete(self,*args):return response
    calls=[];drugs=provider(calls)
    try:
        with pytest.raises(AppError,match=code):await specialty(Nim(),drugs,names=['조플루자'])
        assert calls==[] and _state.get() is None
        assert 'must-not-appear' not in caplog.text and 'invented ingredient' not in caplog.text
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_model_observes_tool_result_then_cannot_repeat_lookup():
    class Nim:
        enabled=True
        def __init__(self):self.seen=False
        async def complete(self,messages,tools):
            self.seen=any(m['role']=='tool' and 'requiresSelection' in m['content'] for m in messages)
            return tool('lookup_products',{'name_id':0},identifier='second' if self.seen else 'first')
    calls=[];drugs=provider(calls);nim=Nim()
    try:
        with pytest.raises(AppError,match='REPEATED_TOOL_CALL'):await specialty(nim,drugs,names=['조플루자','시험약 비'])
        assert nim.seen and len(calls)==1
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_required_label_cannot_be_skipped():
    class Nim:
        enabled=True
        async def complete(self,messages,tools):
            if any(m['role']=='tool' for m in messages):return tool('finish_evidence',identifier='finish')
            return tool('inspect_ingredients',{'product_id':0})
    drugs=provider()
    try:
        product=(await drugs.lookup('조플루자'))['products'][0]
        with pytest.raises(AppError,match='UNSUPPORTED_TOOL'):await specialty(Nim(),drugs,products=[product])
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_missing_key_and_consent_never_call_specialist():
    nim=DrugNim()
    with pytest.raises(AppError,match='MFDS_KEY_REQUIRED'):
        await specialty(nim,SimpleNamespace(enabled=False),names=['조플루자'])
    with pytest.raises(AppError,match='NIM_CONSENT_REQUIRED'):
        await specialty(nim,SimpleNamespace(enabled=True),names=['조플루자'],consent=False)
    assert nim.calls==[]


@pytest.mark.asyncio
async def test_cancel_specialist_stops_model_and_cleans_context():
    entered,cancelled=asyncio.Event(),asyncio.Event()
    class Nim:
        enabled=True
        async def complete(self,*args):
            entered.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
    drugs=provider()
    try:
        task=asyncio.create_task(specialty(Nim(),drugs,names=['조플루자']))
        await asyncio.wait_for(entered.wait(),15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert cancelled.is_set() and _state.get() is None
    finally:await drugs.close()


@pytest.mark.asyncio
async def test_route_and_tools_log_only_safe_metadata():
    stream=io.StringIO();logger=RuntimeLog(stream=stream);drugs=provider()
    try:
        with log_context(logger):
            result=await specialty(DrugNim(),drugs,names=['조플루자'])
        rows=[json.loads(x) for x in stream.getvalue().splitlines()]
        assert any(r['event']=='agent.routed' and r['decision']=='invoke' for r in rows)
        assert [r['tool'] for r in rows if r['event']=='agent.tool']==['lookup_products','finish_evidence']
        assert result['status']=='needs_selection'
        assert any(r['event']=='agent.finalizing' and r['reason']=='required_evidence_complete' for r in rows)
        assert next(r for r in rows if r['event']=='agent.completed')['steps']==1
        assert '조플루자' not in stream.getvalue() and 'test-only' not in stream.getvalue()
    finally:await drugs.close();logger.close()


@pytest.mark.asyncio
async def test_concurrent_specialists_keep_product_evidence_isolated():
    drugs=provider()
    try:
        products=(await drugs.lookup('조플루자'))['products']
        # Bind the native runner once; each task creates its own evidence state.
        async def investigate(**args):
            results=await asyncio.gather(*[
                investigate_if_needed(names=[],products=[p],nim=DrugNim(),drugs=drugs,
                                      emit=lambda *_:None,consent=True) for p in products])
            return {'mode':'nim-react','quotes':[],'results':results}
        with patch('concreteinsure.agent.run_investigation',investigate):
            result=await configured_investigation(nim=DrugNim(),request={'cloudConsent':True})
        assert [r['references'][0]['id'] for r in result['results']]==['mfds-'+p['id'] for p in products]
        assert _state.get() is None and _runner.get() is None
    finally:await drugs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [1, 2])
async def test_lookup_auto_completes_only_after_every_name_even_without_candidates(count):
    class NoCandidates:
        enabled = True
        def __init__(self): self.names = []
        async def lookup(self, name):
            self.names.append(name)
            return {'products': [], 'truncated': False}
    drugs = NoCandidates()
    nim = DrugNim()
    names = ['시험제품 에이', '시험제품 비'][:count]
    result = await specialty(nim, drugs, names=names)
    assert drugs.names == names and nim.calls == ['drug_complete'] * count
    assert result['status'] == 'needs_selection' and result['missingNames'] == names
    assert result['products'] == [] and result['references'] == []


@pytest.mark.asyncio
async def test_multiple_products_require_all_ingredients_and_available_labels():
    drugs = provider()
    nim = DrugNim()
    try:
        products = (await drugs.lookup('조플루자'))['products']
        result = await specialty(nim, drugs, products=products)
        assert nim.calls == ['drug_complete'] * 4
        assert result['status'] == 'ready'
        assert [ref['id'] for ref in result['references']] == ['mfds-' + p['id'] for p in products]
        assert all(any(fact['field'] == 'EE_DOC_DATA' for fact in ref['facts']) for ref in result['references'])
    finally:
        await drugs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('with_ingredients', [True, False])
async def test_no_label_completes_after_detail_without_extra_inference(with_ingredients):
    drugs = provider()
    nim = DrugNim()
    original = drugs.detail
    async def detail(identifier):
        value = await original(identifier)
        if with_ingredients:
            for key in ('EE_DOC_DATA', 'NB_DOC_DATA', 'PN_DOC_DATA'):
                value['documents'][key] = ''
        else:
            value['documents'] = {}
        return value
    drugs.detail = detail
    try:
        product = (await drugs.lookup('조플루자'))['products'][0]
        result = await specialty(nim, drugs, products=[product])
        assert nim.calls == ['drug_complete']
        assert result['status'] == ('ready' if with_ingredients else 'unresolved')
        assert bool(result['specificTerms']) == with_ingredients
    finally:
        await drugs.close()


@pytest.mark.asyncio
async def test_auto_completion_revalidates_reference_integrity(monkeypatch):
    from concreteinsure.agents import drug_agent
    original = drug_agent.reference_from_detail
    def corrupt(*args, **kwargs):
        ref = original(*args, **kwargs)
        ref['facts'][0]['quote'] += ' forged'
        return ref
    monkeypatch.setattr(drug_agent, 'reference_from_detail', corrupt)
    drugs = provider()
    nim = DrugNim()
    try:
        product = (await drugs.lookup('조플루자'))['products'][0]
        with pytest.raises(AppError, match='UNVERIFIED_DRUG_REFERENCE'):
            await specialty(nim, drugs, products=[product])
        assert nim.calls == ['drug_complete'] * 2
        assert _state.get() is None
    finally:
        await drugs.close()


@pytest.mark.asyncio
async def test_last_required_tool_failure_never_auto_completes(monkeypatch):
    from concreteinsure.agents import drug_agent
    original = drug_agent.reference_from_detail
    def invalid_label(detail, *, include_label=True):
        if include_label:
            raise AppError('MFDS_INVALID_DOCUMENT', 502)
        return original(detail, include_label=False)
    monkeypatch.setattr(drug_agent, 'reference_from_detail', invalid_label)
    drugs = provider()
    nim = DrugNim()
    stream = io.StringIO()
    logger = RuntimeLog(stream=stream)
    try:
        product = (await drugs.lookup('조플루자'))['products'][0]
        with log_context(logger), pytest.raises(AppError, match='MFDS_INVALID_DOCUMENT'):
            await specialty(nim, drugs, products=[product])
        assert nim.calls == ['drug_complete'] * 2
        assert 'agent.finalizing' not in stream.getvalue() and 'agent.completed' not in stream.getvalue()
        assert _state.get() is None
    finally:
        await drugs.close()
        logger.close()
