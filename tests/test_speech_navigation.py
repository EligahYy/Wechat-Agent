import pytest
from datetime import datetime,timedelta,timezone
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.repository import archive_page
from wechat_agent.api.messages import read_timeline
from wechat_agent.operations.service import OperationError

def seed(db):
 seed_case(db)
 start=datetime(2026,11,14,tzinfo=timezone.utc)
 archive_page(db,make_page([make_message(message_id=f'speech-{i:03}',sender_id='merchant-a' if i%10==0 else 'provider-p',sent_at=start+timedelta(minutes=i)) for i in range(120)]))

def test_focus_latest_and_cross_page_navigation_keep_other_speakers(db):
 seed(db)
 page=read_timeline(db,'acct-1','merchant-a',focus_latest=True)
 nav=page['speech'];assert nav['current_id']=='speech-110' and nav['index']==nav['total']
 assert nav['next_id'] is None and nav['previous_id']=='speech-100'
 assert any(row['sender']['contact_id']=='provider-p' for row in page['items'])
 older=read_timeline(db,'acct-1','merchant-a',focus_id='speech-060')
 assert older['speech']['next_id']=='speech-070'
 assert len(older['items'])<=50 and older['previous_cursor']
 earlier=read_timeline(db,'acct-1','merchant-a',before_cursor=older['previous_cursor'])
 assert set(row['message_id'] for row in earlier['items']).isdisjoint(row['message_id'] for row in older['items'])

def test_speech_scope_rejects_other_speakers_and_foreign_rooms(db):
 seed(db)
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',focus_id='speech-011')
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',conversation_id='dm-a',focus_id='speech-010')
 result=read_timeline(db,'acct-1','merchant-a',q='does-not-exist',focus_latest=True)
 assert result['speech']['total']==0 and result['speech']['current_id'] is None

def test_matching_uses_id_not_name_and_filters_apply(db):
 seed(db)
 db.execute("UPDATE contacts SET remark='商家甲' WHERE contact_id='provider-p'");db.commit()
 first=read_timeline(db,'acct-1','merchant-a',q='Synthetic',focus_latest=True)
 assert first['speech']['total']==12
 result=read_timeline(db,'acct-1','merchant-a',conversation_id='dm-a',focus_latest=True)
 assert result['speech']['total']<first['speech']['total']

def test_navigation_cursors_are_revision_and_filter_bound(db):
 seed(db)
 page=read_timeline(db,'acct-1','merchant-a',focus_latest=True)
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',before_cursor=page['previous_cursor'],q='different')
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',focus_latest=True,focus_id='speech-010')
 archive_page(db,make_page([make_message(message_id='newest-change')]))
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',before_cursor=page['previous_cursor'])
