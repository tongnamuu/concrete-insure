import pytest
from insurelens.agents.verification import assemble_evidence
from insurelens.core import AppError

def hit(text='😀독감'):
    return {'id':'1:1:3','page':1,'start':1,'end':3,'sourceStart':0,'sourceEnd':3,'quote':text,'matchedText':'독감','segments':[],'offsetEncoding':'unicode-code-points','documentHash':'hash'}
def assemble(hits,**kwargs):return assemble_evidence(hits=hits,mappings=[],references=[],terms=['독감'],mode='nim-react',truncated=False,**kwargs)

def test_unicode_codepoints_and_source_integrity():
    assert assemble([hit()])['quotes'][0]['quote']=='😀독감'
    with pytest.raises(AppError,match='INVALID_SOURCE_SPAN'):assemble([{**hit(),'matchedText':'변경'}])
    with pytest.raises(AppError,match='INVALID_SOURCE_GEOMETRY'):assemble([{**hit(),'segments':[{'start':1,'end':2,'quad':[float('nan')]*8}]}])

def test_invisible_hits_removed_and_coverage_refs_verified():
    invisible={**hit(),'start':0,'end':2,'sourceEnd':2,'quote':'\u200b ','matchedText':'\u200b '}
    assert assemble([invisible])['quotes']==[]
    coverage={'status':'identified','scope':'policy_benefit_only','items':[{'titleId':'missing','clauses':[],'links':[],'checks':[]}],'truncated':False}
    with pytest.raises(AppError,match='INVALID_COVERAGE_SOURCE'):assemble([hit()],coverage=coverage)

@pytest.mark.parametrize('part',['heading','clause','link','check'])
def test_each_coverage_reference_must_point_to_visible_original_quote(part):
    item={'titleId':'1:1:3','clauses':[{'headingId':'1:1:3','sourceIds':['1:1:3']}],'links':[{'sourceIds':['1:1:3']}],'checks':[{'sourceIds':['1:1:3']}]}
    if part=='heading':item['clauses'][0]['headingId']='forged'
    if part=='clause':item['clauses'][0]['sourceIds']=['forged']
    if part=='link':item['links'][0]['sourceIds']=['forged']
    if part=='check':item['checks'][0]['sourceIds']=['forged']
    coverage={'status':'identified','scope':'policy_benefit_only','items':[item],'truncated':False}
    with pytest.raises(AppError,match='INVALID_COVERAGE_SOURCE'):assemble([hit()],coverage=coverage)
