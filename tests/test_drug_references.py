import copy
import pytest
from insurelens.agents.drug_references import resolve_drug_references,verify_drug_references
from insurelens.agents.drug import identify_drugs
from insurelens.core import AppError

def test_brand_reference_is_explicit_sourced_and_immutable():
    result=resolve_drug_references(description='조플루자를 처방받았습니다.')
    assert result['references'] and result['specificTerms']
    for r in result['references']:
        for fact in r['facts']:assert all(t in fact['quote'] for t in fact['terms'])
    forged=copy.deepcopy(result['references']);forged[0]['brand']='changed'
    with pytest.raises(AppError,match='UNVERIFIED_DRUG_REFERENCE'):verify_drug_references(forged)
    assert resolve_drug_references(query='가짜조플루자약')['references']==[]

def test_official_ingredient_salt_is_not_normalized_or_inferred():
    result=identify_drugs([{'id':'200001234','name':'약','ingredients':'오셀타미비르인산염','url':'https://nedrug.mfds.go.kr/item'}])
    assert result['terms']==['오셀타미비르인산염']
    with pytest.raises(AppError,match='UNVERIFIED_PRODUCT'):identify_drugs([{'id':'200001234','name':'약','ingredients':'성분','url':'https://nedrug.mfds.go.kr.evil.example/'}])
