from wechat_agent.context.contracts import ContextCoverage
from wechat_agent.context.builder import build_snapshot
from wechat_agent.profiles.publisher import publish
from wechat_agent.profiles.contracts import ShipmentCandidate,Fact

def test_omitted_batch_goods_retain_valid_fact(db,snapshot,analysis_result,cancellation):
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key='keep',stage='询价',sources=result.goods.volume.sources,goods=[result.goods.volume])]
    assert publish(db,snapshot,result,cancellation).version==1
    current=build_snapshot(db,snapshot.key,snapshot.cutoff,coverage=ContextCoverage())
    result.shipments[0].goods=[]
    assert publish(db,current,result,cancellation).version==2
    import json
    assert json.loads(db.execute('SELECT payload_json FROM shipments').fetchone()[0])['goods']

def test_invalid_retained_batch_evidence_rolls_back_head_and_payload(db,snapshot,cancellation):
    import json
    from wechat_agent.profiles.contracts import AnalysisResult
    from tests.factories import make_message,make_page
    from wechat_agent.source.repository import archive_page
    ref={'message_id':'fixture:dm-a:1','revision':1}
    old=AnalysisResult(contact_id='merchant-a',shipments=[ShipmentCandidate(candidate_key='batch',stage='询价',sources=[ref],goods=[Fact(state='known',value='服装',sources=[ref])])])
    assert publish(db,snapshot,old,cancellation).version==1
    before=db.execute('SELECT payload_json FROM shipments').fetchone()[0]
    archive_page(db,make_page([make_message(message_id='fixture:dm-a:1',conversation_id='dm-a',body='修订后的服装',source_revision='v2')],conversation_id='dm-a',conversation_kind='private'))
    current=build_snapshot(db,snapshot.key,snapshot.cutoff,coverage=ContextCoverage())
    ref2={'message_id':'fixture:dm-a:1','revision':2}
    candidate=AnalysisResult(contact_id='merchant-a',shipments=[ShipmentCandidate(candidate_key='batch',stage='备货',sources=[ref2])])
    outcome=publish(db,current,candidate,cancellation)
    assert outcome.reason=='retained_evidence_unavailable'
    assert db.execute('SELECT version FROM profile_heads').fetchone()[0]==1
    assert db.execute('SELECT payload_json FROM shipments').fetchone()[0]==before
