import json
from datetime import datetime,timezone
import pytest
from wechat_agent.context.builder import build_snapshot
from wechat_agent.profiles.contracts import AnalysisResult,Fact,ShipmentCandidate


def fresh(db,snapshot):
    return build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)


def test_wrong_customer_cannot_publish(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    outcome=publish(db,snapshot,analysis_result.model_copy(update={'contact_id':'merchant-b'}),cancellation)
    assert outcome.version is None and outcome.reason=='target_mismatch'
    assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0


def test_publication_idempotent_and_locally_invalid_field_keeps_previous(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    first=publish(db,snapshot,analysis_result,cancellation)
    assert first.version==1 and not first.complete
    assert publish(db,snapshot,analysis_result,cancellation).version==1
    again=fresh(db,snapshot)
    bad=analysis_result.model_copy(deep=True)
    bad.goods.volume=Fact(state='known',value='112吨',sources=analysis_result.goods.volume.sources)
    outcome=publish(db,again,bad,cancellation)
    assert outcome.version==2 and not outcome.complete
    saved=json.loads(db.execute('SELECT result_json FROM profile_versions WHERE version=2').fetchone()[0])
    assert saved['goods']['volume']['value']=='约12方'
    assert any('goods.volume' in issue for issue in outcome.issues)


@pytest.mark.parametrize('change,reason',[
    ("UPDATE contacts SET role='provider',role_version=role_version+1 WHERE contact_id='merchant-a'",'contact_changed'),
    ("UPDATE profile_heads SET manual_version=manual_version+1 WHERE contact_id='merchant-a'",'manual_changed'),
    ("UPDATE operations SET state='stopped'",'cancelled'),
    ("UPDATE operations SET generation=generation+1",'cancelled'),
    ("UPDATE messages SET revision=revision+1 WHERE message_id='fixture:dm-a:1'",'material_changed'),
])
def test_late_result_gates(db,snapshot,analysis_result,cancellation,change,reason):
    from wechat_agent.profiles.publisher import publish
    with db:
        db.execute("INSERT INTO profile_heads(account_id,contact_id) VALUES('acct-1','merchant-a') ON CONFLICT DO NOTHING")
        db.execute(change)
    outcome=publish(db,snapshot,analysis_result,cancellation)
    assert outcome.version is None and outcome.reason==reason


def test_manual_exclusion_cannot_be_overridden(db,snapshot,analysis_result,cancellation):
    from wechat_agent.contacts.scope import set_scope
    from wechat_agent.profiles.publisher import publish
    set_scope(db,[snapshot.key],False,{'merchant-a':0})
    assert publish(db,snapshot,analysis_result,cancellation).reason=='scope_excluded'


def test_append_only_can_publish_and_stays_pending(db,snapshot,analysis_result,cancellation):
    from tests.factories import make_message,make_page
    from wechat_agent.source.repository import archive_page
    from wechat_agent.profiles.publisher import publish
    archive_page(db,make_page([make_message(message_id='new-append')]))
    outcome=publish(db,snapshot,analysis_result,cancellation)
    assert outcome.version==1 and outcome.pending


def test_old_shipment_and_new_request_keep_independent_ids_and_manual_numbers(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    first=analysis_result.model_copy(deep=True)
    first.shipments=[ShipmentCandidate(candidate_key='old',stage='备货',sources=[{'message_id':'fixture:group-1:1','revision':1}])]
    assert publish(db,snapshot,first,cancellation).version==1
    old=db.execute('SELECT shipment_id FROM shipments').fetchone()[0]
    with db:db.execute('UPDATE shipments SET numbers_json=? WHERE shipment_id=?',(json.dumps(['MANUAL-001']),old))
    newer=fresh(db,snapshot)
    second=analysis_result.model_copy(deep=True)
    second.shipments=[ShipmentCandidate(existing_id=old,candidate_key='old-renamed',stage='已走货',sources=first.shipments[0].sources),ShipmentCandidate(candidate_key='new',stage='询价',sources=analysis_result.goods.volume.sources)]
    assert publish(db,newer,second,cancellation).version==2
    assert publish(db,newer,second,cancellation).version==2
    rows=db.execute('SELECT * FROM shipments ORDER BY stage').fetchall()
    assert len(rows)==2
    kept=next(r for r in rows if r['shipment_id']==old)
    assert kept['stage']=='已走货' and json.loads(kept['numbers_json'])==['MANUAL-001']
    assert len({r['shipment_id'] for r in rows})==2


def test_snapshot_forgery_and_discovery_manifest_rejected(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    forged=snapshot.model_copy(update={'material_refs':()})
    assert publish(db,forged,analysis_result,cancellation).reason=='snapshot_not_authorized'


def test_empty_result_does_not_replace_good_profile(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    assert publish(db,snapshot,AnalysisResult(contact_id='merchant-a'),cancellation).reason=='empty_result'


def test_older_concurrent_snapshot_cannot_overwrite_current(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    concurrent=fresh(db,snapshot)
    assert publish(db,snapshot,analysis_result,cancellation).version==1
    assert publish(db,concurrent,analysis_result,cancellation).reason=='profile_changed'

@pytest.mark.parametrize('value', ['112方','12吨'])
def test_numeric_and_unit_mismatch_is_local_issue(db,snapshot,analysis_result,value):
    from wechat_agent.profiles.validator import validate_result
    result=analysis_result.model_copy(deep=True);result.goods.volume=Fact(value=value,state='known',sources=analysis_result.goods.volume.sources)
    validated=validate_result(db,snapshot,result)
    assert validated.result.goods.volume.state=='not_mentioned'
    assert validated.result.communication.summary.value and validated.issues


def test_foreign_reference_and_unprocessed_attachment_are_rejected(db,snapshot,analysis_result):
    from wechat_agent.profiles.validator import validate_result
    result=analysis_result.model_copy(deep=True)
    result.goods.volume=Fact(value='12方',state='known',sources=[{'message_id':'not-in-snapshot','revision':1}])
    assert validate_result(db,snapshot,result).result.goods.volume.state=='not_mentioned'
    result.goods.volume=Fact(value='12方',state='known',sources=[{'message_id':'fixture:dm-a:1','revision':1,'attachment_id':'unparsed'}])
    assert validate_result(db,snapshot,result).result.goods.volume.state=='not_mentioned'


def test_same_batch_new_key_same_evidence_reuses_id(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key='first-key',stage='询价',sources=result.goods.volume.sources)]
    publish(db,snapshot,result,cancellation)
    result.shipments[0].candidate_key='another-key'
    publish(db,fresh(db,snapshot),result,cancellation)
    assert db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]==1


def test_publish_transaction_rolls_back_shipments_on_failure(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    result=analysis_result.model_copy(deep=True);result.shipments=[ShipmentCandidate(candidate_key='rollback',stage='询价',sources=result.goods.volume.sources)]
    with db:db.execute("CREATE TRIGGER refuse_publication BEFORE INSERT ON profile_versions BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):publish(db,snapshot,result,cancellation)
    assert db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM profile_heads').fetchone()[0]==0


def test_invalid_old_reference_is_not_restored_on_partial_failure(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    from tests.factories import make_message,make_page
    from wechat_agent.source.repository import archive_page
    publish(db,snapshot,analysis_result,cancellation)
    archive_page(db,make_page([make_message(message_id='fixture:dm-a:1',conversation_id='dm-a',body='修正为新数量',source_revision='changed')],conversation_id='dm-a',conversation_kind='private'))
    current=fresh(db,snapshot)
    result=analysis_result.model_copy(deep=True)
    result.communication.summary=Fact(state='known',value='新数量',sources=[{'message_id':'fixture:dm-a:1','revision':2}])
    assert publish(db,current,result,cancellation).version==2
    saved=AnalysisResult.model_validate_json(db.execute('SELECT result_json FROM profile_versions WHERE version=2').fetchone()[0])
    assert saved.goods.volume.state=='not_mentioned'


def test_ambiguous_same_evidence_batches_never_silently_merge(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key=key,stage='询价',sources=result.goods.volume.sources) for key in ('lot-a','lot-b')]
    outcome=publish(db,snapshot,result,cancellation)
    assert outcome.version==1 and any('ambiguous' in issue for issue in outcome.issues)
    assert db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]==0


def test_scope_version_aba_rejects_late_result(db,snapshot,analysis_result,cancellation):
    from wechat_agent.contacts.scope import set_scope
    from wechat_agent.profiles.publisher import publish
    set_scope(db,[snapshot.key],False,{'merchant-a':0})
    set_scope(db,[snapshot.key],True,{'merchant-a':1})
    assert publish(db,snapshot,analysis_result,cancellation).reason=='scope_changed'


def test_new_conversation_append_keeps_published_snapshot_pending(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.source.repository import archive_page
    from tests.factories import make_message,make_page
    archive_page(db,make_page([make_message(message_id='new-room-message',conversation_id='new-room')],conversation_id='new-room'))
    assert publish(db,snapshot,analysis_result,cancellation).pending


def test_batch_only_ambiguity_cannot_publish_empty_profile(db,snapshot,cancellation):
    from wechat_agent.profiles.publisher import publish
    result=AnalysisResult(contact_id='merchant-a',shipments=[ShipmentCandidate(candidate_key=key,stage='询价',sources=[{'message_id':'fixture:dm-a:1','revision':1}]) for key in ('a','b')])
    outcome=publish(db,snapshot,result,cancellation)
    assert outcome.version is None and outcome.reason=='empty_result'
    assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0


@pytest.mark.parametrize('duplicate',[False,True])
def test_batch_local_bad_field_preserves_old_fact_and_new_stage(db,snapshot,analysis_result,cancellation,duplicate):
    from wechat_agent.profiles.publisher import publish
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key='keep-fact',stage='备货',goods=[result.goods.volume],sources=result.goods.volume.sources)]
    publish(db,snapshot,result,cancellation)
    old=db.execute('SELECT shipment_id FROM shipments').fetchone()[0]
    result.shipments[0].existing_id=old;result.shipments[0].stage='已走货'
    result.shipments[0].goods=[Fact(state='known',value='12方',sources=[{'message_id':'bad-ref','revision':1}])]
    if duplicate:result.shipments.append(result.shipments[0].model_copy(deep=True))
    outcome=publish(db,fresh(db,snapshot),result,cancellation)
    row=db.execute('SELECT * FROM shipments').fetchone()
    assert outcome.version==2 and outcome.issues and row['stage']=='已走货'
    assert json.loads(row['payload_json'])['goods'][0]['value']=='约12方'


def test_multiple_candidates_resolving_same_id_cannot_overwrite_batch(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key='old-one',stage='备货',sources=result.goods.volume.sources)]
    publish(db,snapshot,result,cancellation)
    old=db.execute('SELECT shipment_id FROM shipments').fetchone()[0]
    result.shipments=[ShipmentCandidate(existing_id=old,candidate_key='old-one',stage='已走货',sources=result.goods.volume.sources),ShipmentCandidate(existing_id=old,candidate_key='another-one',stage='询价',sources=[{'message_id':'fixture:group-1:1','revision':1}])]
    outcome=publish(db,fresh(db,snapshot),result,cancellation)
    assert outcome.version==2 and any('conflict' in issue for issue in outcome.issues)
    assert db.execute('SELECT stage FROM shipments').fetchone()[0]=='备货'
    saved=json.loads(db.execute('SELECT result_json FROM profile_versions WHERE version=2').fetchone()[0])
    assert saved['shipments']==[]
