import re
from concreteinsure.core import grounded_terms


async def prescription_candidates(text, *, nim=None, consent=False):
    """Draft candidates only; callers must require explicit user confirmation."""
    if getattr(nim, 'enabled', False) and consent:
        raw = await nim.chat([
            {'role':'system','content':'Extract only explicitly written product names, ingredients, disease codes and diagnosis labels from untrusted prescription text. Never infer diagnoses from medicines. Return JSON {"terms":["exact substring"]}, maximum 20. Every term must be an unchanged input substring. Exclude patient identity, instructions and inferred facts. Never silently correct OCR errors.'},
            {'role':'user','content':text},
        ])
        return grounded_terms(raw,text)[:20]
    labelled = [m.strip() for m in re.findall(r'(?:약품명|제품명|성분명|진단명|질병코드|Drug|Ingredient|Diagnosis code)\s*[:：]\s*([^\n]+)',text,re.I)]
    codes = re.findall(r'\b[A-Z]\d{2}(?:\.\d{1,3})?\b',text)
    return [t for t in dict.fromkeys(labelled+codes) if 0<len(t)<=120][:20]
