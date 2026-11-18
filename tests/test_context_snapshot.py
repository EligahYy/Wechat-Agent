from datetime import datetime,timezone
import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.contracts import ContactKey
from wechat_agent.source.repository import archive_page

CUTOFF=datetime(2027,1,1,tzinfo=timezone.utc)
KEY=ContactKey(account_id='acct-1',contact_id='merchant-a')

def test_context_keeps_actual_speakers(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    rows=ContextReader(db,snapshot).messages()
    assert len(rows)==4
    assert {row['sender_id'] for row in rows}=={'merchant-a','provider-p','self-1'}
    assert all(row['conversation_id'] in {'dm-a','group-1'} for row in rows)

def test_snapshot_survives_revisions_and_appends(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    before=ContextReader(db,snapshot).messages()
    old=before[0]
    archive_page(db,make_page([make_message(message_id=old['message_id'],conversation_id=old['conversation_id'],sender_id=old['sender_id'],body='changed',source_revision='new')],conversation_id=old['conversation_id'],conversation_kind='private' if old['conversation_id']=='dm-a' else 'group'))
    archive_page(db,make_page([make_message(message_id='appended',body='new after snapshot')]))
    assert ContextReader(db,snapshot).messages()==before
    assert ContextReader(db,snapshot).resolve(snapshot.material_refs[0])['body']==old['body']

def test_snapshot_rejects_wrong_scope_and_forged_manifest(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    from wechat_agent.context.contracts import SnapshotError
    for forged in [snapshot.model_copy(update={'key':ContactKey(account_id='foreign',contact_id='merchant-a')}),
                   snapshot.model_copy(update={'role_version':999})]:
        with pytest.raises(SnapshotError):ContextReader(db,forged)
    with pytest.raises(SnapshotError):ContextReader(db,snapshot).resolve({'message_id':'not-in-snapshot','revision':1})

def test_snapshot_only_active_merchants(db):
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.context.contracts import SnapshotError
    seed_case(db)
    for identifier in ['provider-p','self-1','not-present']:
        with pytest.raises(SnapshotError):build_snapshot(db,ContactKey(account_id='acct-1',contact_id=identifier),CUTOFF)

def test_snapshot_records_real_material_gaps(db,snapshot):
    from wechat_agent.context.builder import build_snapshot
    db.execute("UPDATE sync_cursors SET complete=0,gaps_json='[\"source_rows_skipped\"]'")
    db.execute("INSERT INTO source_issues(account_id,issue_id,conversation_id,source_revision,code,raw_json) VALUES('acct-1','issue','group-1','1','message_sender_missing','{}')")
    db.commit()
    result=build_snapshot(db,KEY,CUTOFF)
    assert any('source_rows_skipped' in gap for gap in result.gaps)
    assert any('message_sender_missing' in gap for gap in result.gaps)
    assert any('history_complete_unverified' in gap for gap in result.gaps)

def test_snapshot_cutoff_and_equal_time_order_are_stable(db):
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.context.reader import ContextReader
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='z',sent_at=datetime(2028,1,1,tzinfo=timezone.utc)),make_message(message_id='a',sent_at=datetime(2026,1,1,tzinfo=timezone.utc)),make_message(message_id='b',sent_at=datetime(2026,1,1,tzinfo=timezone.utc))]))
    rows=ContextReader(db,build_snapshot(db,KEY,CUTOFF)).messages()
    ids=[row['message_id'] for row in rows]
    assert 'z' not in ids and ids.index('a')<ids.index('b')
    with pytest.raises(ValueError):build_snapshot(db,KEY,datetime(2027,1,1))

def test_snapshot_keeps_replies_and_names_missing_without_guessing(db):
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.context.reader import ContextReader
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='reply',reply_to='unavailable-reference',body='是的')]))
    db.execute("UPDATE contacts SET remark=NULL,nickname=NULL WHERE contact_id='merchant-a'");db.commit()
    current=build_snapshot(db,KEY,CUTOFF)
    rows=ContextReader(db,current).messages()
    assert next(row for row in rows if row['message_id']=='reply')['reply_to']=='unavailable-reference'
    assert any('reply_unavailable' in gap for gap in current.gaps)
    assert ContextReader(db,current).actors()['merchant-a']['name'] is None

def test_snapshot_reader_returns_independent_copies_and_attachment_scope(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    from wechat_agent.context.contracts import SnapshotError
    reader=ContextReader(db,snapshot)
    rows=reader.messages();rows[0]['body']='tampered'
    assert reader.messages()[0]['body']!='tampered'
    ref=snapshot.material_refs[0]
    with pytest.raises(SnapshotError):reader.resolve(ref.model_copy(update={'revision':999}))
    with pytest.raises(SnapshotError):reader.resolve(ref.model_copy(update={'attachment_id':'outside'}))

def test_snapshot_freezes_role_versions_and_explicit_config(db,snapshot):
    from wechat_agent.context.reader import ContextReader
    before=ContextReader(db,snapshot).actors()
    db.execute("UPDATE contacts SET role='platform',role_version=role_version+1 WHERE contact_id='provider-p'");db.commit()
    assert ContextReader(db,snapshot).actors()==before
    assert snapshot.versions['model_config']=='unconfigured'
    assert snapshot.manual_version==0

def test_snapshot_cutoff_preserves_microseconds_and_exact_order(db):
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.context.reader import ContextReader
    seed_case(db)
    archive_page(db,make_page([
        make_message(message_id='a-later',sent_at=datetime.fromisoformat('2026-12-01T00:00:00.000400+00:00')),
        make_message(message_id='z-earlier',sent_at=datetime.fromisoformat('2026-12-01T08:00:00.000000+08:00'))]))
    early=build_snapshot(db,KEY,datetime.fromisoformat('2026-12-01T00:00:00.000100+00:00'))
    assert 'a-later' not in {row['message_id'] for row in ContextReader(db,early).messages()}
    later=build_snapshot(db,KEY,datetime.fromisoformat('2026-12-01T00:00:00.001000+00:00'))
    ordered=[row['message_id'] for row in ContextReader(db,later).messages()]
    assert ordered.index('z-earlier')<ordered.index('a-later')

def test_snapshot_retains_authorized_cross_conversation_reply_context(db):
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.context.reader import ContextReader
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='cross-room-reply',reply_to='fixture:dm-a:1',body='按私信的需求报价')]))
    current=build_snapshot(db,KEY,CUTOFF);reader=ContextReader(db,current)
    reply=next(row for row in reader.messages() if row['message_id']=='cross-room-reply')
    original=reader.resolve({'message_id':reply['reply_to'],'revision':1})
    assert original['conversation_id']=='dm-a'
    assert not any('reply_unavailable:cross-room-reply'==gap for gap in current.gaps)


@pytest.mark.parametrize('extra_messages', [1, 1_000, 10_000])
def test_unchanged_published_snapshot_skips_body_reads_and_duplicates(db, extra_messages, record_property):
    from time import perf_counter
    from tests.profile_seed import seed_profile
    from wechat_agent.context.builder import build_snapshot

    seed_case(db)
    for start in range(0, extra_messages, 500):
        archive_page(db, make_page([
            make_message(message_id=f'bulk-{index}', body='合成业务材料')
            for index in range(start, min(start + 500, extra_messages))
        ]))
    first = perf_counter()
    seed_profile(db, reuse_published=True)
    record_property('build_and_publish_ms', round((perf_counter() - first) * 1000, 2))
    snapshot_id = db.execute('SELECT snapshot_id FROM snapshots').fetchone()[0]
    statements = []
    db.set_trace_callback(statements.append)
    first = perf_counter()
    try:
        frozen = build_snapshot(db, KEY, CUTOFF, reuse_published=True)
    finally:
        db.set_trace_callback(None)
    record_property('reuse_ms', round((perf_counter() - first) * 1000, 2))
    assert frozen.id == snapshot_id
    assert db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 1
    assert not any('message_revisions r JOIN' in sql or 'payload_json' in sql for sql in statements)
    assert sum('FROM attachments a JOIN' in sql for sql in statements) == 2

    archive_page(db, make_page([make_message(message_id='bulk-0', body='已修订', source_revision='2')]))
    assert build_snapshot(db, KEY, CUTOFF, reuse_published=True).id != frozen.id
