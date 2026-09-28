"""Source-bound MFDS references. No product catalog or model-authored drug facts."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from concreteinsure.core import ensure

# Dosage may explicitly name the ingredient basis; it is never dosing advice.
LABEL_FIELDS = ('UD_DOC_DATA', 'PN_DOC_DATA', 'NB_DOC_DATA', 'EE_DOC_DATA')


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


def document_fragments(xml):
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

    def visit(node, path):
        # MFDS sometimes stores the entire indication in ARTICLE/@title with
        # no PARAGRAPH children. Keep the attribute verbatim and its locator.
        title = node.get('title', '')
        if node.tag in {'SECTION', 'ARTICLE'} and title.strip():
            result.append({'text': title, 'path': path + '/@title'})
        if node.tag == 'PARAGRAPH':
            raw = ''.join(node.itertext())
            if re.search(r'<(?:/?(?:p|table|tbody|tr|td|th|br|span|div|sup|sub|b|i|strong)\b)', raw, re.I):
                parser = PlainHTML()
                parser.feed(raw)
                raw = ''.join(parser.parts)
            if raw.strip():
                result.append({'text': raw, 'path': path})
            return
        counts = {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            visit(child, f'{path}/{child.tag}[{counts[child.tag]}]')

    visit(root, '/' + root.tag)
    return result


def paragraphs(xml):
    """Ordered source text, including section/article title attributes."""
    return [fragment['text'] for fragment in document_fragments(xml)]


def reference_from_detail(detail, *, include_label=True):
    """Extract only structured ingredients and explicit, narrowly supported relations."""
    product, documents = detail['product'], detail['documents']
    facts = []

    def fact(kind, label, field, ordinal, quote, terms, priority, source_path=None):
        ensure(all(t in quote for t in terms), 'UNGROUNDED_REFERENCE_TERM', 502)
        facts.append({'kind': kind, 'label': label, 'quote': quote, 'page': None,
                      'terms': list(dict.fromkeys(terms)), 'priority': priority,
                      'field': field, 'paragraph': ordinal, 'sourcePath': source_path or field,
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

    ingredient_terms = [t for f in facts for t in f['terms']]
    dose_terms = set()
    for field in (LABEL_FIELDS if include_label else ()):
        for ordinal, fragment in enumerate(document_fragments(documents.get(field, ''))):
            text, path = fragment['text'], fragment['path']
            # Preserve the whole source fragment. Never join separated spans.
            if len(text) > 2500 or len(facts) >= 12:
                continue
            if field == 'UD_DOC_DATA':
                # An explicit "X로서 75 mg" basis in this selected product's
                # dosage document may connect a structured salt name to X.
                # X must also occur literally in its structured ingredient;
                # incidental co-medications, negation and guessed salt removal
                # are not accepted. Keep the full sentence as the evidence.
                match = re.search(r'(?:^|[,（(]\s*)(?:이\s*약은\s*)?([가-힣A-Za-z][가-힣A-Za-z-]{1,79}?)(?:으로서|로서)\s*\d+(?:\.\d+)?\s*(?:mg|g|μg|µg|mcg|밀리그램|그램|마이크로그램)(?![A-Za-z])', text, re.I)
                if match and not re.search(r'않|아니|불명|추정|가능성|제외|대신|병용|함께|다른', text):
                    term = match.group(1)
                    if term not in dose_terms and any(term in name for name in ingredient_terms):
                        fact('dose_basis', '식약처 용법·용량의 성분 기준 원문', field, ordinal, text, [term], 'specific', path)
                        dose_terms.add(term)
            elif field == 'EE_DOC_DATA':
                heading = re.fullmatch(r'\s*(?:\d+[.)]\s*)?(.{2,100}?)의 치료\s*', text)
                if heading:
                    subject = heading.group(1)
                    terms = [subject] + [t for t in re.findall(r'[가-힣A-Za-z]{2,}', subject) if t not in {'감염증', '환자', '성인', '소아'}]
                    fact('indication', '식약처 효능·효과 원문', field, ordinal, text, terms, 'context', path)
                elif text.strip():
                    # Source-bound infection wording is search context only,
                    # never a diagnosis or an assertion of treatment eligibility.
                    terms = [] if '예방' in text else re.findall(
                        r'([가-힣A-Za-z]{2,40})(?:\s+[A-Z])?\s+바이러스\s+감염증', text)
                    fact('indication_context', '식약처 효능·효과 원문', field, ordinal, text, terms, 'context', path)
            elif '전구약물' in text:
                match = re.search(r'이\s*약은\s*전구약물로[^.!?\n]{0,300}?활성 대사(?:물|체)\s+([가-힣A-Za-z][가-힣A-Za-z -]{0,80}?)(?:으로|로)\s*전환된다[.]', text)
                if match and not re.search(r'않|아니|불명|추정|가능성', text):
                    fact('active_metabolite', '식약처 설명서의 성분 연결 원문', field, ordinal, text, [match.group(1)], 'specific', path)

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
