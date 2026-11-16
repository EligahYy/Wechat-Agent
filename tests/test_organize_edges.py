import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.repository import archive_metadata,archive_page
from wechat_agent.source.contracts import ContactKey,ConversationRecord
from wechat_agent.contacts.conversations import resolve_contact_conversations
from wechat_agent.source.coverage import assess_sync
from wechat_agent.source.sync import SyncResult


def test_departed_member_without_speech_is_no_longer_in_known_scope(db):
    seed_case(db)
    db.execute("INSERT INTO contacts(account_id,contact_id) VALUES('acct-1','silent-person')")
    db.commit()
    room=ConversationRecord(account_id='acct-1',conversation_id='only-member',kind='group',title='群',membership_state='known',member_ids=['silent-person'])
    archive_metadata(db,'acct-1',[],[room])
    key=ContactKey(account_id='acct-1',contact_id='silent-person')
    assert 'only-member' in resolve_contact_conversations(db,key)
    archive_metadata(db,'acct-1',[],[room.model_copy(update={'member_ids':[]})])
    assert 'only-member' not in resolve_contact_conversations(db,key)

@pytest.mark.parametrize('shared',[False,True])
def test_failed_shared_room_blocks_exactly_dependent_contacts(db,shared):
    seed_case(db)
    db.execute("DELETE FROM members WHERE account_id='acct-1' AND contact_id='merchant-b' AND conversation_id='group-1'")
    db.execute("DELETE FROM message_revisions WHERE account_id='acct-1' AND message_id IN (SELECT message_id FROM messages WHERE account_id='acct-1' AND conversation_id='group-1' AND sender_id='merchant-b')")
    db.execute("DELETE FROM messages WHERE account_id='acct-1' AND conversation_id='group-1' AND sender_id='merchant-b'")
    db.execute("INSERT INTO conversations(account_id,conversation_id,kind,title) VALUES('acct-1','dm-b','private','B')")
    db.execute("INSERT INTO members VALUES('acct-1','dm-b','merchant-b','source_membership')")
    if shared:db.execute("INSERT INTO members VALUES('acct-1','group-1','merchant-b','source_membership')")
    result=SyncResult(successful_conversations=['dm-a','dm-b'],failed_conversations=['group-1'],gaps=['source_timeout'])
    assessment=assess_sync(db,'acct-1',{'merchant-a','merchant-b'},result)
    assert not assessment.global_blocked
    assert not assessment.contacts['merchant-a'].can_analyze
    assert assessment.contacts['merchant-b'].can_analyze is not shared
