from datetime import datetime
import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.repository import archive_page
from wechat_agent.api.messages import read_timeline

def seed(db):
 seed_case(db)
 archive_page(db,make_page([make_message(message_id='before-midnight',sent_at=datetime.fromisoformat('2026-11-14T15:59:59+00:00')),make_message(message_id='after-midnight',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-14T16:00:00+00:00'))]))

def test_calendar_local_days_and_latest(db):
 from wechat_agent.messages.calendar import read_calendar
 seed(db)
 result=read_calendar(db,'acct-1','merchant-a','2026-11')
 assert result['days']['2026-11-14']==1 and '2026-11-15' not in result['days']
 assert result['latest_day']=='2026-11-14'
 assert read_calendar(db,'acct-1','merchant-a','2026-12')['days']=={}

def test_day_scope_keeps_other_people_and_cursor_bound(db):
 seed(db)
 result=read_timeline(db,'acct-1','merchant-a',day='2026-11-15',date_latest=True)
 assert result['items']==[]
 assert result['speech']['total']==0
 assert read_timeline(db,'acct-1','merchant-a',day='2026-11-14')['speech']['total']==1
 assert read_timeline(db,'acct-1','merchant-a',day='2026-11-16')['total']==0
 with pytest.raises(Exception):read_timeline(db,'acct-1','merchant-a',day='not-a-date')

def test_calendar_source_scope_and_foreign_contact(db):
 from wechat_agent.messages.calendar import read_calendar
 from wechat_agent.operations.service import OperationError
 seed(db)
 assert read_calendar(db,'acct-1','merchant-a','2026-11',conversation_id='dm-a')['latest_day']=='2026-11-11'
 with pytest.raises(OperationError):read_calendar(db,'foreign','merchant-a','2026-11')
 with pytest.raises(OperationError):read_calendar(db,'acct-1','merchant-a','2026-11',conversation_id='foreign-room')

def test_day_cursors_cannot_cross_dates_and_latest_keeps_author_navigation(db):
 from wechat_agent.operations.service import OperationError
 seed(db)
 # Exact ordering includes other people's newest message, not just target speech.
 result=read_timeline(db,'acct-1','merchant-a',day='2026-11-15',date_latest=True)
 assert result['items']==[]
 # Build a full day and verify directional cursors bind the local day.
 from datetime import timedelta
 start=datetime.fromisoformat('2026-11-14T01:00:00+00:00')
 archive_page(db,make_page([make_message(message_id=f'day-page-{i}',sent_at=start+timedelta(minutes=i)) for i in range(60)]))
 result=read_timeline(db,'acct-1','merchant-a',day='2026-11-14',date_latest=True)
 assert len(result['items'])<=50 and result['previous_cursor']
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',day='2026-11-15',before_cursor=result['previous_cursor'])

def test_latest_window_without_target_speech_navigates_back_to_nearest_author(db):
 seed_case(db)
 from datetime import timedelta
 start=datetime.fromisoformat('2026-11-14T01:00:00+00:00')
 archive_page(db,make_page([make_message(message_id=f'late-tail-{i}',sender_id='merchant-a' if i<2 else 'provider-p',sent_at=start+timedelta(minutes=i)) for i in range(80)]))
 result=read_timeline(db,'acct-1','merchant-a',day='2026-11-14',date_latest=True)
 assert result['speech']['previous_id']=='late-tail-1'
 assert result['speech']['next_id'] is None
 assert not any(row['sender']['contact_id']=='merchant-a' for row in result['items'])
