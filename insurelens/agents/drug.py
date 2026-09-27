import re
from urllib.parse import urlsplit
from insurelens.core import ensure


def identify_drugs(products=None):
    products = products or []
    ensure(isinstance(products, list) and len(products) <= 5, 'INVALID_PRODUCTS')
    for p in products:
        url = urlsplit(p.get('url', ''))
        ensure(bool(re.fullmatch(r'\d{5,20}', p.get('id', ''))) and isinstance(p.get('name'), str) and isinstance(p.get('ingredients'), str) and url.scheme == 'https' and url.hostname == 'nedrug.mfds.go.kr', 'UNVERIFIED_PRODUCT')
    terms = [t.strip() for p in products for t in re.split(r'[|;,\n]', p['ingredients']) if 1 < len(t.strip()) <= 120]
    return {'mappings': products, 'terms': list(dict.fromkeys(terms))}
