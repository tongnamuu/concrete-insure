import math
import unicodedata
from concreteinsure.core import ensure, NOTICE
from .drug_references import verify_drug_references


def visible(text):
    return any(not c.isspace() and not unicodedata.category(c).startswith('C') for c in text)


def assemble_evidence(*, hits, mappings, references, terms, mode, truncated, coverage=None):
    coverage = coverage or {'status': 'unresolved', 'scope': 'policy_benefit_only', 'items': [], 'truncated': False}
    for h in hits:
        ensure(h.get('offsetEncoding') == 'unicode-code-points' and isinstance(h.get('quote'), str) and isinstance(h.get('matchedText'), str) and 0 <= h['sourceStart'] <= h['start'] <= h['end'] <= h['sourceEnd'], 'INVALID_SOURCE_SPAN')
        ensure(h['quote'][h['start'] - h['sourceStart']:h['end'] - h['sourceStart']] == h['matchedText'], 'INVALID_SOURCE_SPAN')
        ensure(all(s['start'] >= h['start'] and s['end'] <= h['end'] and (s['quad'] is None or (len(s['quad']) == 8 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in s['quad']))) for s in h['segments']), 'INVALID_SOURCE_GEOMETRY')
    hits = [h for h in hits if visible(h['quote'])]
    ids = {h['id'] for h in hits}
    for item in coverage['items']:
        ensure(item['titleId'] in ids and all(c['headingId'] in ids and all(i in ids for i in c['sourceIds']) for c in item['clauses']) and all(all(i in ids for i in link['sourceIds']) for link in item['links']) and all(all(i in ids for i in check['sourceIds']) for check in item['checks']), 'INVALID_COVERAGE_SOURCE')
    return {'coverage': coverage, 'quotes': hits, 'mappings': mappings, 'references': verify_drug_references(references), 'terms': terms, 'notice': NOTICE, 'mode': mode, 'truncated': truncated}
