from datetime import datetime
import pytest
from tests.factories import seed_case,make_page,make_message
from wechat_agent.source.repository import archive_page
from wechat_agent.api.messages import read_timeline
from wechat_agent.messages.calendar import read_calendar
from wechat_agent.operations.service import OperationError

def test_membership_alone_does_not_make_unrelated_group_a_message_source(db):
 seed_case(db)
 archive_page(db,make_page([make_message(message_id='unrelated',conversation_id='directory-only',sender_id='provider-p')],conversation_id='directory-only',conversation_kind='group'))
 db.execute("INSERT INTO members(account_id,conversation_id,contact_id) VALUES('acct-1','directory-only','merchant-a')");db.commit()
 result=read_timeline(db,'acct-1','merchant-a')
 assert 'directory-only' not in {row['conversation_id'] for row in result['sources']}
 assert 'unrelated' not in {row['message_id'] for row in result['items']}
 with pytest.raises(OperationError):read_timeline(db,'acct-1','merchant-a',conversation_id='directory-only')

def test_real_group_does_not_admit_context_only_days(db):
 seed_case(db)
 archive_page(db,make_page([make_message(message_id='context-day',sender_id='provider-p',sent_at=datetime.fromisoformat('2026-11-14T12:00:00+08:00'))]))
 calendar=read_calendar(db,'acct-1','merchant-a','2026-11',conversation_id='group-1')
 assert calendar['days'].get('2026-11-14',0)==0 and calendar['speech_days'].get('2026-11-14',0)==0
 assert calendar['speech_days']['2026-11-11']>0
 result=read_timeline(db,'acct-1','merchant-a',day='2026-11-14',conversation_id='group-1')
 assert result['total']==0 and result['speech']['total']==0

def test_private_outgoing_only_conversation_remains_accessible(db):
 seed_case(db)
 # The existing private relationship has only our side in this revision.
 db.execute("UPDATE messages SET sender_id='self-1' WHERE conversation_id='dm-a'");db.commit()
 assert any(row['conversation_id']=='dm-a' for row in read_timeline(db,'acct-1','merchant-a')['sources'])
