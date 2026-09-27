"""Bounded conversation context assembled only from server-owned successful turns."""
import json

MAX_TURNS = 4
MAX_CONTEXT_CHARS = 24000
MAX_SOURCES = 2
MAX_QUOTE_CHARS = 1200


def model_context(turns):
    selected, size = [], 0
    for turn in reversed([t for t in turns if t['state'] == 'completed' and not (t.get('result') or {}).get('requiresDrugSelection')][-MAX_TURNS:]):
        result = turn.get('result') or {}
        sources = []
        for hit in result.get('quotes', []):
            quote = hit.get('quote', '')
            if not quote.strip():
                continue
            sources.append({'id': hit['id'], 'page': hit['page'],
                            'quote': quote[:MAX_QUOTE_CHARS], 'truncated': len(quote) > MAX_QUOTE_CHARS})
            if len(sources) == MAX_SOURCES:
                break
        item = {'query': turn['query'], 'description': turn['description'],
                'confirmedTerms': turn['confirmedTerms'],
                'terms': result.get('terms', []), 'sources': sources}
        length = len(json.dumps(item, ensure_ascii=False))
        if size + length > MAX_CONTEXT_CHARS:
            break
        selected.append(item)
        size += length
    return list(reversed(selected))


def literal_context(conversation):
    """History can supply exact search strings, never inferred patient facts."""
    return [text for turn in conversation for text in (
        turn['query'], turn['description'], *turn['confirmedTerms'], *turn['terms'],
        *(source['quote'] for source in turn['sources']))]
