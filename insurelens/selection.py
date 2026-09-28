"""Server-owned continuation after product selection; never client-supplied facts."""
import json
from .core import QueryRequest, ensure, grounded_terms
from .conversation import literal_context


def validate_saved_facts(facts, request, conversation):
    request = QueryRequest.model_validate(request).model_dump()
    ensure(isinstance(facts, dict) and set(facts) == {'query', 'description', 'terms', 'drugNames'}, 'SELECTION_STATE_INVALID', 409)
    ensure(facts['query'] == request['query'] and facts['description'] == request['description'], 'SELECTION_STATE_INVALID', 409)
    fields = [request['query'], request['description'], *request['confirmedTerms'],
              *(s for t in conversation or [] for s in (t['query'], t['description'], *t['confirmedTerms']))]
    names = facts['drugNames']
    ensure(isinstance(names, list) and len(names) <= 5 and all(isinstance(n, str) and n.strip() and 2 <= len(n) <= 120 and
           any(n in field for field in fields) for n in names), 'SELECTION_STATE_INVALID', 409)
    # Input extraction can append up to 20 confirmed terms to the 25 model terms.
    terms = facts['terms']
    ensure(isinstance(terms, list) and len(terms) <= 45, 'SELECTION_STATE_INVALID', 409)
    for start in range(0, len(terms), 25):
        grounded_terms(json.dumps({'terms': terms[start:start+25]}), request['query'], request['confirmedTerms'],
                       request['description'], context=literal_context(conversation or []))
    return facts


def selection_snapshot(*, facts, request, conversation, products, document):
    validate_saved_facts(facts, request, conversation)
    return {'version': 1, 'facts': facts, 'request': {k: v for k, v in request.items() if k != 'cloudConsent'},
            'conversation': conversation or [], 'products': {p['id']: p for p in products},
            'documentHash': document['hash'] if 'hash' in document else document.get('documentHash')}
