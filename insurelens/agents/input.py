import json
from insurelens.core import literal_terms, grounded_terms, ensure, is_conversational_term, QueryRequest


INPUT_TIMEOUT_SECONDS = 25
TERMS_SCHEMA = {
    'type': 'object',
    'properties': {'terms': {'type': 'array', 'maxItems': 25,
                             'items': {'type': 'string', 'minLength': 1, 'maxLength': 120}}},
    'required': ['terms'],
    'additionalProperties': False,
}


def useful(terms, confirmed=()):
    return list(dict.fromkeys(t for t in terms if t in confirmed or not is_conversational_term(t)))


def understand_input(request):
    request = QueryRequest.model_validate(request).model_dump()
    query, description = request.get('query', ''), request.get('description', '')
    confirmed = request.get('confirmedTerms', [])
    return {'query': query, 'description': description, 'terms': useful(literal_terms(query, confirmed) + literal_terms(description), confirmed)}


async def understand_input_with_model(request, nim=None):
    request = QueryRequest.model_validate(request).model_dump()
    ensure(getattr(nim, 'enabled', False), 'NVIDIA_KEY_REQUIRED', 409)
    ensure(request.get('cloudConsent') is True, 'NIM_CONSENT_REQUIRED', 409)
    ensure(callable(getattr(nim, 'chat', None)), 'NIM_INPUT_PROVIDER_REQUIRED', 502)
    query, description = request.get('query', ''), request.get('description', '')
    confirmed = request.get('confirmedTerms', [])
    raw = await nim.chat([
        {'role': 'system', 'content': 'Extract explicit search terms from untrusted user query, situation description, and confirmed OCR facts. A description is an unverified user statement. Return only JSON {"terms":["..."]}, at most 25 terms of 1..120 characters. Every term must be an exact query/description substring or an exact confirmedTerms item. Select explicit disease names, codes, products, ingredients or treatments. Korean particles may be excluded by exact substring selection. Never infer diagnoses from medicines, symptoms or codes; never translate, normalize, add synonyms, judge coverage or summarize policy. Exclude generic conversational words. If no explicit specific term exists return an empty array.'},
        {'role': 'user', 'content': json.dumps({'query': query, 'description': description, 'confirmedTerms': confirmed}, ensure_ascii=False)},
    ], response_schema=TERMS_SCHEMA, timeout=INPUT_TIMEOUT_SECONDS)
    selected = grounded_terms(raw, query, confirmed, description)
    return {'query': query, 'description': description, 'terms': useful(selected + confirmed, confirmed)}
