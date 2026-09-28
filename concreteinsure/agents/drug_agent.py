"""Conditionally invoked medicine evidence agent; state never comes from model prose."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from concreteinsure.core import AppError, ensure
from concreteinsure.diagnostics import record
from concreteinsure.progress import model_progress
from .drug import identify_drugs
from .drug_references import reference_from_detail, verify_drug_references

SKILL = (Path(__file__).resolve().parents[2] / 'skills/drug-ingredient-resolver/SKILL.md').read_text()
_runner: ContextVar[Any] = ContextVar('concreteinsure_drug_runner', default=None)
_state: ContextVar[Any] = ContextVar('concreteinsure_drug_state', default=None)


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class NameArgs(EmptyArgs):
    name_id: int = Field(ge=0, le=4)


class ProductArgs(EmptyArgs):
    product_id: int = Field(ge=0, le=4)


SCHEMAS = {
    'medicine__lookup_products': NameArgs,
    'medicine__inspect_ingredients': ProductArgs,
    'medicine__inspect_label': ProductArgs,
}


def empty_result():
    return {'status': 'skipped', 'references': [], 'specificTerms': [], 'contextTerms': [],
            'products': [], 'requiresSelection': False, 'missingNames': []}


@dataclass
class DrugState:
    names: list[str]
    products: list[dict]
    nim: Any
    drugs: Any
    emit: Any
    lookups: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    references: dict = field(default_factory=dict)
    inspected_labels: set = field(default_factory=set)
    call_ids: set = field(default_factory=set)
    plans: int = 0
    result: dict | None = None

    @property
    def missing(self):
        return {i: n for i, n in enumerate(self.names)
                if not any(n.casefold() in p['name'].casefold() for p in self.products)}

    @property
    def completion_ready(self):
        """Decide from successful tool state, never from model text or elapsed time."""
        if self.missing:
            return set(self.lookups) == set(self.missing)
        expected = set(range(len(self.products)))
        if not expected or set(self.details) != expected or set(self.references) != expected:
            return False
        return all(i in self.inspected_labels or not any(
            detail['documents'].get(key) for key in ('EE_DOC_DATA', 'NB_DOC_DATA', 'PN_DOC_DATA'))
            for i, detail in self.details.items())

    def plan(self, response):
        """Reject unsafe calls before framework validation can echo model arguments."""
        ensure(self.plans < 12, 'DRUG_AGENT_STEP_LIMIT', 502)
        self.plans += 1
        ensure(isinstance(response, dict), 'NIM_INVALID_RESPONSE', 502)
        message = response.get('message', {})
        ensure(isinstance(message, dict), 'NIM_INVALID_RESPONSE', 502)
        ensure(message.get('role') == 'assistant', 'NIM_INVALID_RESPONSE', 502)
        ensure(response.get('finish_reason') == 'tool_calls', 'DRUG_AGENT_UNFINISHED', 502)
        calls = message.get('tool_calls')
        ensure(isinstance(calls, list) and len(calls) == 1, 'INVALID_TOOL_ARGUMENTS', 502)
        call = calls[0]
        ensure(isinstance(call, dict), 'INVALID_TOOL_ARGUMENTS', 502)
        fn = call.get('function', {})
        ensure(isinstance(fn, dict), 'INVALID_TOOL_ARGUMENTS', 502)
        name, identifier = fn.get('name'), call.get('id')
        ensure(call.get('type') == 'function' and name in SCHEMAS, 'UNSUPPORTED_TOOL', 502)
        ensure(isinstance(identifier, str) and 0 < len(identifier) <= 200 and identifier not in self.call_ids,
               'REPEATED_TOOL_CALL', 502)
        try:
            args = SCHEMAS[name].model_validate_json(fn['arguments']).model_dump()
        except (KeyError, TypeError, ValueError, ValidationError):
            raise AppError('INVALID_TOOL_ARGUMENTS', 502) from None
        self.call_ids.add(identifier)
        return {'name': name, 'args': args, 'id': identifier, 'type': 'tool_call'}

    async def lookup(self, name_id):
        ensure(name_id in self.missing, 'UNGROUNDED_DRUG_NAME', 502)
        ensure(name_id not in self.lookups, 'REPEATED_TOOL_CALL', 502)
        result = await self.drugs.lookup(self.names[name_id])
        for product in result['products']:
            identify_drugs([product])
        self.lookups[name_id] = result
        return {'name_id': name_id, 'products': result['products'], 'truncated': result.get('truncated', False),
                'requiresSelection': True}

    async def ingredients(self, product_id):
        ensure(not self.missing and 0 <= product_id < len(self.products), 'UNVERIFIED_PRODUCT', 502)
        ensure(product_id not in self.details, 'REPEATED_TOOL_CALL', 502)
        detail = await self.drugs.detail(self.products[product_id]['id'])
        ensure(detail['product']['id'] == self.products[product_id]['id'], 'MFDS_PRODUCT_MISMATCH', 502)
        self.details[product_id] = detail
        ref = reference_from_detail(detail, include_label=False)
        self.references[product_id] = ref
        return {'product_id': product_id, 'facts': ref['facts'], 'source': ref['source'],
                'labelAvailable': any(detail['documents'].get(k) for k in ('EE_DOC_DATA', 'NB_DOC_DATA', 'PN_DOC_DATA'))}

    async def label(self, product_id):
        ensure(product_id in self.details, 'DRUG_DETAIL_REQUIRED', 502)
        ensure(product_id not in self.inspected_labels, 'REPEATED_TOOL_CALL', 502)
        ref = reference_from_detail(self.details[product_id])
        self.references[product_id] = ref
        self.inspected_labels.add(product_id)
        return {'product_id': product_id, 'facts': ref['facts'], 'source': ref['source']}

    def finish(self):
        if self.missing:
            ensure(set(self.lookups) == set(self.missing), 'DRUG_EVIDENCE_INCOMPLETE', 502)
            products = {p['id']: p for r in self.lookups.values() for p in r['products']}
            self.result = {**empty_result(), 'status': 'needs_selection', 'requiresSelection': True,
                           'products': list(products.values()),
                           'missingNames': [self.names[i] for i, r in self.lookups.items() if not r['products']],
                           'truncated': any(r.get('truncated', False) for r in self.lookups.values())}
        else:
            ensure(set(self.details) == set(range(len(self.products))), 'DRUG_EVIDENCE_INCOMPLETE', 502)
            for i, detail in self.details.items():
                if any(detail['documents'].get(k) for k in ('EE_DOC_DATA', 'NB_DOC_DATA', 'PN_DOC_DATA')):
                    ensure(i in self.inspected_labels, 'DRUG_LABEL_REQUIRED', 502)
            refs = [self.references[i] for i in range(len(self.products))]
            verify_drug_references(refs)
            def terms(priority):
                return list(dict.fromkeys(t for r in refs for f in r['facts'] if f['priority'] == priority for t in f['terms']))
            self.result = {**empty_result(), 'status': 'ready' if terms('specific') else 'unresolved',
                           'references': refs, 'specificTerms': terms('specific'), 'contextTerms': terms('context'),
                           'products': [self.details[i]['product'] for i in range(len(self.products))]}
        return 'drug_evidence_complete'


def current_state():
    state = _state.get()
    ensure(state is not None and state.result is None, 'DRUG_AGENT_CONTEXT_REQUIRED', 503)
    return state


async def investigate_if_needed(*, names, products, nim, drugs, emit, consent):
    ensure(consent is True, 'NIM_CONSENT_REQUIRED', 409)
    ensure(getattr(nim, 'enabled', False), 'NVIDIA_KEY_REQUIRED', 409)
    products = products or []
    identify_drugs(products)
    ensure(isinstance(names, list) and len(names) <= 5 and all(isinstance(n, str) and 2 <= len(n) <= 120 for n in names),
           'INVALID_DRUG_NAMES')
    reason = 'selected_product' if products else ('explicit_drug_name' if names else 'no_drug_information')
    record('agent.routed', agent='drug_evidence', decision='invoke' if names or products else 'skip', reason=reason)
    if not names and not products:
        return empty_result()
    ensure(getattr(drugs, 'enabled', False), 'MFDS_KEY_REQUIRED', 409)
    runner = _runner.get()
    ensure(runner is not None, 'DRUG_AGENT_RUNTIME_REQUIRED', 503)
    state = DrugState(names=list(dict.fromkeys(names)), products=products, nim=nim, drugs=drugs, emit=emit)
    token = _state.set(state)
    try:
        payload = {'task': 'drug_evidence', 'names': [{'name_id': i, 'name': n} for i, n in state.missing.items()],
                   'selectedProducts': [{'product_id': i, 'name': p['name']} for i, p in enumerate(products)],
                   'requiresSelection': bool(state.missing)}
        await model_progress(runner.ainvoke(json.dumps(payload, ensure_ascii=False)),
                             emit=emit, stage='drug_reference', label='검색 2단계')
        ensure(state.result is not None, 'DRUG_AGENT_UNFINISHED', 502)
        verify_drug_references(state.result['references'])
        record('agent.completed', agent='drug_evidence', status_name=state.result['status'], steps=state.plans)
        return state.result
    finally:
        _state.reset(token)
