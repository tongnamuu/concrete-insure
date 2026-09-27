"""Source-bound MFDS references. No product catalog or model-authored drug facts."""
import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from insurelens.core import ensure


class VerifiedReference(dict):
    """In-process provenance marker; never constructed from web request data."""
    def seal(self):
        self._digest = self.digest()
        return self

    def digest(self):
        return hashlib.sha256(json.dumps(self, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'br', 'p', 'tr', 'li', 'td', 'th'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p', 'tr', 'li', 'td', 'th'}:
            self.parts.append('\n')


def paragraphs(xml):
    """Decode provider XML/CDATA without rewriting its text or fetching resources."""
    ensure(isinstance(xml, str) and len(xml) <= 1_000_000, 'MFDS_DOCUMENT_LIMIT', 502)
    if not xml.strip():
        return []
    ensure(not re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I), 'MFDS_INVALID_DOCUMENT', 502)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        ensure(False, 'MFDS_INVALID_DOCUMENT', 502)
    result = []
    for node in root.iter('PARAGRAPH'):
        raw = ''.join(node.itertext())
        if re.search(r'<(?:/?(?:p|table|tbody|tr|td|th|br|span|div|sup|sub|b|i|strong)\b)', raw, re.I):
            parser = PlainHTML()
            parser.feed(raw)
            raw = ''.join(parser.parts)
        if raw.strip():
            result.append(raw)
    return result


def reference_from_detail(detail):
    """Extract only structured ingredients and explicit, narrowly supported relations."""
    product, documents = detail['product'], detail['documents']
    facts = []

    def fact(kind, label, field, ordinal, quote, terms, priority):
        ensure(all(t in quote for t in terms), 'UNGROUNDED_REFERENCE_TERM', 502)
        facts.append({'kind': kind, 'label': label, 'quote': quote, 'page': None,
                      'terms': list(dict.fromkeys(terms)), 'priority': priority,
                      'field': field, 'paragraph': ordinal,
                      'documentHash': hashlib.sha256(documents[field].encode()).hexdigest()})

    # Codes delimit ingredients in MFDS MAIN_ITEM_INGR. Keep the actual name,
    # including salts, prodrugs and formulation qualifiers, unchanged.
    raw = documents.get('MAIN_ITEM_INGR', '')
    names = [x.strip() for x in re.split(r'\[[A-Za-z0-9]+\]|[|;\n]', raw) if x.strip()]
    names = [x for x in names if len(x) <= 120]
    if names:
        fact('ingredient', '식약처 유효성분 원문', 'MAIN_ITEM_INGR', 0, raw, names, 'specific')
    else:
        raw = documents.get('ITEM_INGR_NAME', '')
        names = [x.strip() for x in re.split(r'[|;\n]', raw) if 1 < len(x.strip()) <= 120]
        if names:
            fact('ingredient', '식약처 주성분 원문', 'ITEM_INGR_NAME', 0, raw, names, 'specific')
        else:
            for field, text in documents.items():
                if field.startswith('MTRAL_NM:') and 1 < len(text) <= 120:
                    fact('ingredient', '식약처 주성분 상세 원문', field, 0, text, [text], 'specific')

    for field in ('PN_DOC_DATA', 'NB_DOC_DATA', 'EE_DOC_DATA'):
        for ordinal, text in enumerate(paragraphs(documents.get(field, ''))):
            # Selection is literal. Preserve the entire paragraph as evidence;
            # do not fabricate a short quote by joining separated spans.
            if len(text) > 2500 or len(facts) >= 12:
                continue
            if field == 'EE_DOC_DATA':
                heading = re.fullmatch(r'\s*(?:\d+[.)]\s*)?(.{2,100}?)의 치료\s*', text)
                if heading:
                    subject = heading.group(1)
                    terms = [subject] + [t for t in re.findall(r'[가-힣A-Za-z]{2,}', subject) if t not in {'감염증', '환자', '성인', '소아'}]
                    fact('indication', '식약처 효능·효과 원문', field, ordinal, text, terms, 'context')
                elif text.strip():
                    fact('indication_context', '식약처 효능·효과 원문', field, ordinal, text, [], 'context')
            elif '전구약물' in text:
                # Never strip a suffix or infer equivalence. Unsupported wording
                # and negated/uncertain relations remain unresolved.
                match = re.search(r'이\s*약은\s*전구약물로[^.!?\n]{0,300}?활성 대사(?:물|체)\s+([가-힣A-Za-z][가-힣A-Za-z -]{0,80}?)(?:으로|로)\s*전환된다[.]', text)
                if match and not re.search(r'않|아니|불명|추정|가능성', text):
                    fact('active_metabolite', '식약처 설명서의 성분 연결 원문', field, ordinal, text, [match.group(1)], 'specific')

    value = VerifiedReference(id='mfds-' + product['id'], brand=product['name'], aliases=[product['name']],
        scope='product_reference', source={'publisher': '식품의약품안전처', 'url': product['url'],
            'type': 'mfds_label', 'documentDate': detail.get('changeDate') or None,
            'checkedAt': detail['retrievedAt'], 'retrievedAt': detail['retrievedAt'],
            'permitDate': product.get('permitDate'), 'cancelDate': product.get('cancelDate'),
            'status': detail.get('status'), 'historicalApproval': 'unverified'}, facts=facts)
    return value.seal()


def verify_drug_references(references):
    ensure(isinstance(references, list) and len(references) <= 5, 'INVALID_DRUG_REFERENCES')
    for ref in references:
        ensure(isinstance(ref, VerifiedReference) and ref.digest() == ref._digest, 'UNVERIFIED_DRUG_REFERENCE')
        ensure(all(t in f['quote'] for f in ref['facts'] for t in f['terms']), 'UNGROUNDED_REFERENCE_TERM')
    return references


async def resolve_drug_references(*, products=None, drug_names=None, drugs=None):
    products, drug_names = products or [], drug_names or []
    ensure(len(products) <= 5 and len(drug_names) <= 5, 'DRUG_RESULT_LIMIT')
    if not products and not drug_names:
        return {'references': [], 'specificTerms': [], 'contextTerms': [], 'products': [], 'requiresSelection': False, 'missingNames': []}
    ensure(drugs is not None and drugs.enabled, 'MFDS_KEY_REQUIRED', 409)
    # Selection is always explicit, including a search yielding a single item.
    missing = [n for n in drug_names if not any(n.casefold() in p['name'].casefold() for p in products)]
    if missing:
        candidates, unmatched, truncated = {}, [], False
        for name in missing:
            response = await drugs.lookup(name)
            truncated |= response.get('truncated', False)
            if not response['products']:
                unmatched.append(name)
            candidates.update({p['id']: p for p in response['products']})
        return {'references': [], 'specificTerms': [], 'contextTerms': [], 'products': list(candidates.values()),
                'requiresSelection': True, 'missingNames': unmatched, 'truncated': truncated}
    # Independent selected products can be fetched concurrently, with a bound.
    gate = asyncio.Semaphore(2)
    async def fetch(product):
        async with gate:
            return await drugs.detail(product['id'])
    tasks = [asyncio.create_task(fetch(p)) for p in products]
    try:
        details = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    references = [reference_from_detail(d) for d in details]
    verify_drug_references(references)
    def terms(priority):
        return list(dict.fromkeys(t for r in references for f in r['facts'] if f['priority'] == priority for t in f['terms']))
    return {'references': references, 'specificTerms': terms('specific'), 'contextTerms': terms('context'),
            'products': [d['product'] for d in details], 'requiresSelection': False, 'missingNames': []}
