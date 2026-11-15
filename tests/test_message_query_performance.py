"""Correct scope and bounded read work, independent of wall-clock CPU speed."""
from datetime import datetime,timedelta,timezone
import sqlite3
import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.repository import archive_page
from wechat_agent.messages.calendar import read_calendar
from wechat_agent.api.messages import read_timeline


def test_group_context_is_bound_to_target_speech_on_selected_day(db):
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='only-others-today',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-12T10:00:00+08:00'))]))
    assert read_calendar(db,'acct-1','merchant-a','2026-11')['days'].get('2026-11-12',0)==0
    assert read_timeline(db,'acct-1','merchant-a',day='2026-11-12')['total']==0
    archive_page(db,make_page([make_message(message_id='target-today',sent_at=datetime.fromisoformat('2026-11-12T11:00:00+08:00'))]))
    result=read_timeline(db,'acct-1','merchant-a',day='2026-11-12',q='Synthetic')
    assert {r['message_id'] for r in result['items']}=={'target-today','only-others-today'}


def test_search_does_not_determine_authored_room_scope(db):
    seed_case(db)
    assert {r['message_id'] for r in read_timeline(db,'acct-1','merchant-a',day='2026-11-11',q='已发出')['items']}=={'fixture:group-1:1','fixture:group-1:2'}
    archive_page(db,make_page([make_message(message_id='own-unmatched',body='question',sent_at=datetime.fromisoformat('2026-11-12T11:00:00+08:00')),make_message(message_id='other-match',body='answer',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-12T11:01:00+08:00'))]))
    assert [r['message_id'] for r in read_timeline(db,'acct-1','merchant-a',day='2026-11-12',q='answer')['items']]==['other-match']


def test_author_and_date_revision_remove_old_calendar_dot(db):
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='revised',sent_at=datetime.fromisoformat('2026-11-13T12:00:00+08:00'))]))
    assert read_calendar(db,'acct-1','merchant-a','2026-11')['days']['2026-11-13']==1
    archive_page(db,make_page([make_message(message_id='revised',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-14T12:00:00+08:00'),source_revision='source-v2')]))
    result=read_calendar(db,'acct-1','merchant-a','2026-11')
    assert '2026-11-13' not in result['days'] and '2026-11-14' not in result['days']
    assert result['latest_day']=='2026-11-11'


def test_outgoing_private_has_latest_fallback_without_faking_blue_dot(db):
    seed_case(db)
    db.execute("UPDATE messages SET sender_id='self-1' WHERE sender_id='merchant-a'");db.commit()
    result=read_calendar(db,'acct-1','merchant-a','2026-11')
    assert result['days']=={} and result['latest_day']=='2026-11-11'
    result=read_timeline(db,'acct-1','merchant-a',day=result['latest_day'])
    assert result['total']==2 and result['speech']['total']==0


def test_unrelated_conversation_count_does_not_multiply_message_scans(db):
    seed_case(db)
    stamp=datetime(2025,1,1,tzinfo=timezone.utc)
    with db:
        db.executemany("INSERT INTO conversations(account_id,conversation_id,kind) VALUES('acct-1',?,'group')",[(f'noise-{i}',) for i in range(200)])
        db.executemany("INSERT INTO messages(account_id,message_id,conversation_id,sender_id,sent_at,kind,body,source_revision,raw_json) VALUES('acct-1',?,'group-1','merchant-a',?,'text','performance','v1','{}')",[(f'history-{i}',(stamp+timedelta(minutes=i)).isoformat()) for i in range(10000)])
    ticks=0
    def budget():
        nonlocal ticks
        ticks+=1
        return int(ticks>3000)
    db.set_progress_handler(budget,1000)
    try:
        read_calendar(db,'acct-1','merchant-a','2026-11')
        read_timeline(db,'acct-1','merchant-a',day='2026-11-11',date_latest=True)
    except sqlite3.OperationalError as exc:
        pytest.fail(f'read exceeded 3M SQLite instructions: {exc}')
    finally:db.set_progress_handler(None,0)


def test_window_positions_supply_exact_local_neighbors_and_ranks(db):
    seed_case(db)
    start=datetime(2026,11,14,tzinfo=timezone.utc)
    archive_page(db,make_page([make_message(message_id=f'pos-{i:03}',sender_id='merchant-a' if i%3==0 else 'provider-p',sent_at=start+timedelta(minutes=i)) for i in range(120)]))
    result=read_timeline(db,'acct-1','merchant-a',day='2026-11-14',focus_id='pos-060')
    positions=result['speech']['positions']
    assert positions and len(positions)==len([r for r in result['items'] if r['sender']['contact_id']=='merchant-a'])
    focus=next(p for p in positions if p['current_id']=='pos-060')
    assert (focus['index'],focus['previous_id'],focus['next_id'])==(21,'pos-057','pos-063')
    assert positions[0]['previous_id'] is not None and positions[-1]['next_id'] is not None


def test_another_group_only_has_context_when_target_speaks_there_today(db):
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='a-old',conversation_id='group-a',sent_at=datetime.fromisoformat('2026-11-10T11:00:00+08:00')),make_message(message_id='a-context',conversation_id='group-a',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-11T11:00:00+08:00'))],conversation_id='group-a'))
    result=read_timeline(db,'acct-1','merchant-a',day='2026-11-11')
    assert 'group-a' in {s['conversation_id'] for s in result['sources']}
    assert 'a-context' not in {r['message_id'] for r in result['items']}
    assert any(r['sender']['contact_id']=='provider-p' for r in result['items'])


def test_same_instant_offsets_use_beijing_day_and_stable_id(db):
    seed_case(db)
    archive_page(db,make_page([make_message(message_id='offset-a',sent_at=datetime.fromisoformat('2026-11-14T16:00:00+00:00')),make_message(message_id='offset-b',sent_at=datetime.fromisoformat('2026-11-15T00:00:00+08:00')),make_message(message_id='offset-c',sent_at=datetime.fromisoformat('2026-11-14T11:00:00-05:00'))]))
    assert read_calendar(db,'acct-1','merchant-a','2026-11')['days']['2026-11-15']==3
    assert [r['message_id'] for r in read_timeline(db,'acct-1','merchant-a',day='2026-11-15')['items']]==['offset-a','offset-b','offset-c']


def test_attachment_page_is_batched_and_keeps_file_states(db):
    seed_case(db)
    with db:
        db.executemany("INSERT INTO attachments(account_id,attachment_id,message_id,state,mime,reason) VALUES('acct-1',?,?,'failed','text/plain','synthetic-failure')",[(f'att-{i}',f'fixture:group-1:{i}') for i in (1,2)])
    queries=[];db.set_trace_callback(queries.append)
    try:result=read_timeline(db,'acct-1','merchant-a',day='2026-11-11')
    finally:db.set_trace_callback(None)
    attachment_reads=[q for q in queries if 'FROM attachments' in q]
    assert len(attachment_reads)==1
    assert sum(len(r['attachments']) for r in result['items'])==2
    assert all(a['state']=='failed' and not a['downloadable'] and a['reason']=='synthetic-failure' for r in result['items'] for a in r['attachments'])
