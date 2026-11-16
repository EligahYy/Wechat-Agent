from wechat_agent.profiles.contracts import AnalysisResult

def candidate(ref,value='收纳盒'):
    return AnalysisResult.model_validate({'contact_id':'p','goods':{'products':{'value':value,'state':'known','sources':[{'message_id':ref,'revision':1}]}}})

def test_identical_field_facts_are_losslessly_coalesced_with_all_citations():
    from wechat_agent.analysis.facts import deduplicate
    data=deduplicate([candidate('a'),candidate('b'),candidate('a'),candidate('c','玻璃杯')])
    products=[item['goods']['products'] for item in data if 'goods' in item and 'products' in item['goods']]
    assert len(products)==2
    assert {r['message_id'] for r in products[0]['sources']}=={'a','b'}
    assert products[1]['value']=='玻璃杯'
