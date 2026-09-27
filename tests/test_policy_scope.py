from insurelens.agents.policy_scope import describe_policy_scope

def hit(ident,text):return {'id':ident,'quote':text}
def section(payment='독감으로 진단받고 치료하면 보험금을 지급합니다.'):
    heading=hit('heading','보험금 지급사유')
    return {'id':'section','title':hit('title','독감 치료 특약'),'clauses':[{'kind':'payment','heading':heading,'hits':[heading,hit('body',payment)]}], 'truncated':False}

def test_benefit_scope_has_only_source_links_and_unconfirmed_conditions():
    result=describe_policy_scope(sections=[section()],terms=['독감'])
    assert result['status']=='identified' and result['scope']=='policy_benefit_only'
    item=result['items'][0]
    assert item['links'][0]['sourceIds']==['body']
    assert all(c['status']=='needs_confirmation' for c in item['checks'])

def test_exclusion_or_heading_alone_does_not_establish_benefit():
    for text in ['보험금 지급사유','독감은 보험금을 지급하지 않습니다.','독감은 제외하며 다른 항목은 지급합니다.']:
        assert describe_policy_scope(sections=[section(text)],terms=['독감'])['status']=='unresolved'
