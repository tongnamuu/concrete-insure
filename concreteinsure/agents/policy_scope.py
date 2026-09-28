import re
import unicodedata
from concreteinsure.core import ensure
from concreteinsure.pdf import pdf_operation
from .drug_references import verify_drug_references
from .verification import visible


def normalize(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('C'))


def ambiguous(text):
    return bool(re.search('제외|인정하지|해당하지|지급하지|보장하지|보상하지', normalize(text)))


def unique(values):
    return list(dict.fromkeys(values))


def describe_policy_scope(*, sections=None, references=None, terms=None, truncated=False):
    references, terms = references or [], terms or []
    verify_drug_references(references)
    items = []
    for section in sections or []:
        clauses = [c for c in section['clauses'] if c['kind'] in {'payment', 'definition', 'exclusion', 'claim'} and c['hits']]
        payment = [h for c in clauses if c['kind'] == 'payment' for h in c['hits']]
        if not re.search('지급합니다|지급합니|보상합니다|보상합니', normalize(''.join(h['quote'] for h in payment))):
            continue
        definition = [h for c in clauses if c['kind'] == 'definition' for h in c['hits']]
        positive = [h for h in payment + definition if not ambiguous(h['quote'])]
        links = []
        for reference in references:
            brand_hits = [h for h in positive if any(a in h['quote'] for a in reference['aliases'])]
            if brand_hits:
                links.append({'kind': 'direct_brand', 'referenceId': reference['id'], 'label': reference['brand'], 'term': reference['brand'], 'sourceIds': unique(h['id'] for h in brand_hits)})
                continue
            context = [t for f in reference['facts'] if f['priority'] == 'context' for t in f['terms']]
            if not any(t in section['title']['quote'] or any(t in h['quote'] for h in payment) for t in context):
                continue
            for term in [t for f in reference['facts'] if f['priority'] == 'specific' for t in f['terms']]:
                matched = [h for h in definition if term in h['quote'] and not ambiguous(h['quote'])]
                if matched:
                    links.append({'kind': 'ingredient', 'referenceId': reference['id'], 'label': reference['brand'], 'term': term, 'sourceIds': unique(h['id'] for h in matched)})
        if not links:
            supplied = {t for r in references for f in r['facts'] for t in f['terms']}
            for term in [t for t in terms if t not in supplied]:
                matched = [h for h in payment if term in h['quote'] and not ambiguous(h['quote'])]
                if term in section['title']['quote'] and matched:
                    links.append({'kind': 'explicit_term', 'referenceId': None, 'label': term, 'term': term, 'sourceIds': unique(h['id'] for h in matched)})
        if not links:
            continue
        all_hits = [h for c in clauses for h in c['hits']]
        checks = [{'kind': 'enrollment', 'sourceIds': [section['title']['id']], 'status': 'needs_confirmation'}]
        for kind, pattern in [('period','보험기간|보장개시|면책기간'),('diagnosis','진단'),('treatment','처방|치료|수술|입원'),('limit','연간|회한|횟수|한도|최초'),('approval_date','허가|진단당시')]:
            ids = unique(h['id'] for h in all_hits if re.search(pattern, normalize(h['quote'])))
            if ids:
                checks.append({'kind': kind, 'sourceIds': ids, 'status': 'needs_confirmation'})
        checks.append({'kind': 'exclusion', 'sourceIds': unique(h['id'] for c in clauses if c['kind'] == 'exclusion' for h in c['hits']), 'status': 'needs_confirmation'})
        cross_ids = unique(h['id'] for h in all_hits if re.search('보통약관|별표|준용', h['quote']))
        if cross_ids:
            checks.append({'kind': 'cross_reference', 'sourceIds': cross_ids, 'status': 'needs_confirmation'})
        items.append({'id': section['id'], 'titleId': section['title']['id'], 'links': links, 'clauses': [{'kind': c['kind'], 'headingId': c['heading']['id'], 'sourceIds': unique(h['id'] for h in c['hits'])} for c in clauses], 'checks': checks, 'truncated': bool(section.get('truncated'))})
    return {'status': 'identified' if items else 'unresolved', 'scope': 'policy_benefit_only', 'items': items, 'truncated': bool(truncated)}


async def inspect_policy_scope(*, document, hits, terms, references, operation=pdf_operation):
    anchors, seen = [], set()
    for h in hits:
        key = (h['page'], h['sourceStart'], h['sourceEnd'])
        if key not in seen and visible(h['quote']):
            anchors.append(h)
            seen.add(key)
        if len(anchors) == 12:
            break
    if not anchors:
        return {'coverage': describe_policy_scope(), 'hits': []}
    result = await operation({'op': 'sections', 'pdf': document['pdf'], 'index': document['index'], 'anchors': anchors})
    ensure(isinstance(result.get('sections'), list), 'INVALID_POLICY_SECTIONS')
    coverage = describe_policy_scope(sections=result['sections'], truncated=result.get('truncated', False), references=references, terms=terms)
    included = {item['id'] for item in coverage['items']}
    hits = [h for s in result['sections'] if s['id'] in included for h in [s['title'], *(h for c in s['clauses'] for h in c['hits'])]]
    return {'coverage': coverage, 'hits': hits}
