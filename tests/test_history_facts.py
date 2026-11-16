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

def test_fallback_merge_cannot_drop_a_meaningful_input_field():
    import pytest
    from wechat_agent.analysis.facts import enforce_merge_scope
    from wechat_agent.model.contracts import ModelCallError
    with pytest.raises(ModelCallError) as error:
        enforce_merge_scope(AnalysisResult(contact_id='p'),'goods.products',[candidate('a').model_dump()])
    assert error.value.code=='history_merge_incomplete'


def test_fallback_shipments_may_resolve_an_authorized_existing_batch():
    from wechat_agent.analysis.facts import enforce_merge_scope
    ref={'message_id':'source','revision':1}
    original={'contact_id':'p','shipments':[{'candidate_key':'order-ref','stage':'备货','sources':[ref]}]}
    resolved=AnalysisResult.model_validate(original)
    resolved.shipments[0].existing_id='authorized-existing'
    # Existing-id authorization is still enforced by validate_unit / publisher;
    # candidate membership must not prevent the merge from proposing that match.
    enforce_merge_scope(resolved,'shipments',[original])

def test_reused_reader_cannot_authorize_a_different_snapshot(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.profiles.validator import validate_result
    reader=ContextReader(db,snapshot)
    another=build_snapshot(db,snapshot.key,snapshot.cutoff)
    assert validate_result(db,another,AnalysisResult(contact_id=snapshot.key.contact_id),reader=reader).reason=='snapshot_not_authorized'


def test_all_field_merge_cannot_silently_omit_an_extracted_field():
    import pytest
    from wechat_agent.analysis.facts import enforce_merge_scope
    from wechat_agent.model.contracts import ModelCallError
    original=candidate('a')
    original.goods.category=original.goods.products.model_copy()
    reduced=candidate('a')
    with pytest.raises(ModelCallError) as error:enforce_merge_scope(reduced,'all',[original.model_dump()])
    assert error.value.code=='history_merge_incomplete'
