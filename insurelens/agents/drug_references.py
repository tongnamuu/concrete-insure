import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from insurelens.core import ensure

CATALOG = json.loads((Path(__file__).resolve().parents[2] / 'data/drug-references.json').read_text())
for item in CATALOG:
    url = urlsplit(item['source']['url'])
    ensure(url.scheme == 'https' and url.hostname in {'www.roche.co.kr', 'assets.roche.com'} and item['scope'] == 'product_reference', 'INVALID_REFERENCE_SOURCE')
    for fact in item['facts']:
        ensure(all(t in fact['quote'] for t in fact['terms']), 'UNGROUNDED_REFERENCE_TERM')


def resolve_drug_references(query='', description='', confirmed_terms=None, products=None):
    values = [query, description, *(confirmed_terms or []), *(p['name'] for p in products or [])]
    references = []
    for item in CATALOG:
        if any(re.search(r'(?:^|[^\w])' + re.escape(alias) + r'(?=$|[^\w]|를|을|은|는|이|가|도|와|과|정|캡슐|현탁|처방)', text, re.I) for alias in item['aliases'] for text in values):
            references.append(item)
    def terms(priority):
        return list(dict.fromkeys(t for r in references for f in r['facts'] if f['priority'] == priority for t in f['terms']))
    return {'references': copy.deepcopy(references), 'specificTerms': terms('specific'), 'contextTerms': terms('context')}


def verify_drug_references(references):
    ensure(isinstance(references, list) and len(references) <= len(CATALOG), 'INVALID_DRUG_REFERENCES')
    for ref in references:
        ensure(ref in CATALOG, 'UNVERIFIED_DRUG_REFERENCE')
    return references
