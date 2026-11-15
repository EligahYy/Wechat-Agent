import asyncio
from datetime import timedelta
import pytest
from tests.factories import seed_case,make_message,make_page
from tests.test_business_scope import NOW,KEY
from wechat_agent.source.repository import archive_page
from wechat_agent.source.contracts import ContactKey

def prepare(db):
    seed_case(db)
    db.execute("UPDATE contacts SET role='unknown'");db.commit()
    archive_page(db,make_page([make_message(message_id='demand',sent_at=NOW,body='我有12方收纳盒，需要德国含税报价')]))
    from wechat_agent.discovery.context import build_discovery_snapshot
    return build_discovery_snapshot(db,KEY,NOW,versions={'model_config':'test-model-v1'})

def test_request_without_direct_interaction_uses_own_author_evidence(db):
    from wechat_agent.discovery.repository import publish_discovery
    from wechat_agent.discovery.contracts import DiscoveryResult
    from wechat_agent.contacts.scope import classify_scope
    snapshot=prepare(db)
    result=DiscoveryResult(contact_id=KEY.contact_id,intent='request',sources=[{'message_id':'demand','revision':1}])
    assert publish_discovery(db,snapshot,result).state=='published'
    assert 'group_demand' in classify_scope(db,KEY,NOW).reasons
    assert db.execute("SELECT role FROM contacts WHERE contact_id='merchant-a'").fetchone()[0]=='unknown'

def test_foreign_author_revision_and_late_excluded_results_rejected(db):
    from wechat_agent.discovery.repository import publish_discovery
    from wechat_agent.discovery.contracts import DiscoveryResult
    from wechat_agent.contacts.scope import set_scope
    snapshot=prepare(db)
    def result(message='demand',revision=1):return DiscoveryResult(contact_id='merchant-a',intent='request',sources=[{'message_id':message,'revision':revision}])
    assert publish_discovery(db,snapshot,result(revision=2)).state=='rejected'
    assert publish_discovery(db,snapshot,result(message='fixture:group-1:2')).state=='rejected'
    set_scope(db,[KEY],False,{'merchant-a':0})
    assert publish_discovery(db,snapshot,result()).state=='manual_excluded'
    assert db.execute('SELECT COUNT(*) FROM business_signals').fetchone()[0]==0

def test_negative_requires_complete_coverage_and_current_material(db):
    from wechat_agent.discovery.repository import publish_discovery
    from wechat_agent.discovery.contracts import DiscoveryResult
    from wechat_agent.contacts.scope import classify_scope
    snapshot=prepare(db)
    db.execute("UPDATE sync_cursors SET complete=0");db.commit()
    from wechat_agent.discovery.context import build_discovery_snapshot
    snapshot=build_discovery_snapshot(db,KEY,NOW,versions={'model_config':'test-model-v1'})
    negative=DiscoveryResult(contact_id='merchant-a',intent='advertisement',sources=[{'message_id':'demand','revision':1}])
    assert publish_discovery(db,snapshot,negative).state=='published'
    assert classify_scope(db,KEY,NOW).provisional  # no sync cursor = incomplete window
    archive_page(db,make_page([make_message(message_id='demand',sent_at=NOW,body='修订的需求',source_revision='changed')]))
    assert publish_discovery(db,snapshot,negative).state=='stale'

def test_snapshot_rejects_naive_time_and_self(db):
    from wechat_agent.discovery.context import build_discovery_snapshot
    seed_case(db)
    with pytest.raises(ValueError):build_discovery_snapshot(db,KEY,NOW.replace(tzinfo=None),versions={'model_config':'test'})
    with pytest.raises(ValueError):build_discovery_snapshot(db,ContactKey(account_id='acct-1',contact_id='self-1'),NOW,versions={'model_config':'test'})

@pytest.mark.asyncio
async def test_classifier_uses_discovery_purpose_and_unknown_target(db):
    from types import SimpleNamespace
    from wechat_agent.discovery.classifier import DiscoveryStrategy
    from wechat_agent.model.contracts import ModelCallError
    snapshot=prepare(db)
    class Gateway:
        config=SimpleNamespace(capabilities=SimpleNamespace(max_output_tokens=2048))
        async def generate(self,request,cancellation):
            assert request.purpose=='discovery' and request.unit_id.startswith('discovery:')
            assert '我有12方' in request.messages[-1].content
            return SimpleNamespace(payload={'contact_id':'merchant-a','intent':'request','sources':[{'message_id':'demand','revision':1}]})
    result=await DiscoveryStrategy(db,Gateway()).classify(snapshot,None)
    assert result.intent=='request'

def test_reply_outside_neighbor_window_is_included_or_marks_gap(db):
    from wechat_agent.discovery.context import build_discovery_snapshot
    import json
    prepare(db)
    archive_page(db,make_page([make_message(message_id='reply-to-absent',sent_at=NOW,reply_to='unavailable-reference')]))
    snapshot=build_discovery_snapshot(db,KEY,NOW,versions={'model_config':'test'})
    assert any('reply' in gap for gap in snapshot.gaps)

def test_distant_same_room_reply_is_closed_without_missing_gap(db):
    from wechat_agent.discovery.context import build_discovery_snapshot
    import json
    prepare(db)
    rows=[make_message(message_id='original-demand',sender_id='provider-p',sent_at=NOW-timedelta(hours=1),body='需要德国运输？')]
    rows += [make_message(message_id=f'filler-{i}',sender_id='provider-p',sent_at=NOW-timedelta(minutes=30-i)) for i in range(10)]
    rows += [make_message(message_id='own-reply',sent_at=NOW,reply_to='original-demand',body='是的，帮我报价')]
    archive_page(db,make_page(rows))
    snapshot=build_discovery_snapshot(db,KEY,NOW,versions={'model_config':'test'})
    assert 'original-demand' in {ref.message_id for ref in snapshot.material_refs}
    assert not any('reply_unavailable:own-reply'==gap for gap in snapshot.gaps)
