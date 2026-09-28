from concreteinsure.core import ensure
from concreteinsure.pdf import pdf_operation


async def retrieve_policy(*, document, terms, ids, pages=None, operation=pdf_operation):
    ensure(isinstance(ids, list) and 0 < len(ids) <= 25 and all(type(i) is int and 0 <= i < len(terms) for i in ids), 'UNGROUNDED_TERM')
    payload = {'op': 'search', 'pdf': document['pdf'], 'index': document['index'], 'terms': [terms[i] for i in dict.fromkeys(ids)]}
    if pages is not None:
        payload['pages'] = pages
    return await operation(payload)
