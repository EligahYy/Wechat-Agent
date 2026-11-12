"""Malformed source identities are not people; legacy evidence remains intact."""
from contextlib import closing
from importlib.resources import files
import json

import pytest
from pydantic import ValidationError

from tests.factories import make_message, make_page
from tests.fakes.source import FakeSource
from tests.test_source_adapter import NativeServer, adapter
from tests.test_source_probe import message
from wechat_agent.source.contracts import ContactKey, ContactRecord

BAD_ID='<msg><appmsg appid="" sdkver="0"><title>synthetic payload'

@pytest.mark.asyncio
async def test_xml_sender_is_quarantined_without_losing_raw_or_advancing_cursor(db):
    from wechat_agent.source.repository import archive_page
    server=NativeServer();server.rows=[{**message(1,talker='room@chatroom'),'sender':BAD_ID}]
    async with adapter(server) as source:
        page=await source.messages('room@chatroom',None,20)
    assert page.records==[]
    assert page.issues[0].code=='message_sender_invalid'
    assert page.issues[0].raw['sender']==BAD_ID
    archive_page(db,page)
    assert db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM source_issues').fetchone()[0]==1
    assert tuple(db.execute('SELECT cursor,complete FROM sync_cursors').fetchone())==(None,0)

@pytest.mark.parametrize('sender',[BAD_ID,'plain text content','x\nxml','bad\ufffdid','x'*513])
def test_message_contract_rejects_payload_identity(sender):
    with pytest.raises(ValidationError):make_message(sender_id=sender)

@pytest.mark.parametrize('sender',['person-legacy','wxid_example_1','123456789@openim','legacy.alias'])
def test_valid_legacy_and_enterprise_ids_are_preserved(sender):
    assert make_message(sender_id=sender).sender_id==sender

def test_system_event_with_broken_source_identity_remains_unattributed():
    from wechat_agent.source.wx_cli import parse_message
    raw={**message(1,talker='room@chatroom'),'sender':BAD_ID,'msg_type':10000}
    parsed=parse_message(raw,'account-a')
    assert parsed.sender_id is None
    assert parsed.raw==raw

def old_database(path):
    from wechat_agent.storage.db import open_db,_execute_script
    conn=open_db(path)
    conn.execute('CREATE TABLE schema_version(singleton INTEGER PRIMARY KEY,version INTEGER NOT NULL)')
    for name in ('001_archive.sql','002_source_sync.sql','003_operations.sql'):
        _execute_script(conn,files('wechat_agent.storage').joinpath('migrations',name).read_text())
    conn.execute('INSERT INTO schema_version VALUES(1,3)')
    conn.execute("INSERT INTO accounts(account_id) VALUES('acct-1')")
    conn.execute("INSERT INTO contacts(account_id,contact_id,role,role_version) VALUES('acct-1',?,'merchant',2)",(BAD_ID,))
    conn.execute("INSERT INTO contacts(account_id,contact_id,remark) VALUES('acct-1','123456789@openim','昵称🌙')")
    conn.execute("INSERT INTO conversations(account_id,conversation_id,kind) VALUES('acct-1','group-1','group')")
    conn.execute("""INSERT INTO messages(account_id,message_id,conversation_id,sender_id,sent_at,kind,body,source_revision,raw_json)
        VALUES('acct-1','legacy-message','group-1',?,'2026-11-11T00:00:00+00:00','text','original body','v1',?)""",(BAD_ID,json.dumps({'sender':BAD_ID})))
    conn.commit()
    return conn

def test_schema3_upgrade_quarantines_bad_people_preserving_history_and_manual_roles(tmp_path):
    from wechat_agent.storage.db import migrate
    from wechat_agent.contacts.service import list_contacts,set_roles
    from wechat_agent.operations.service import create_operation,OperationError
    from wechat_agent.operations.contracts import OperationScope
    with closing(old_database(tmp_path/'old.sqlite3')) as conn:
        migrate(conn);migrate(conn)
        row=conn.execute('SELECT identity_state,role,role_version FROM contacts WHERE contact_id=?',(BAD_ID,)).fetchone()
        assert tuple(row)==('quarantined','merchant',2)
        assert conn.execute('SELECT body FROM messages').fetchone()[0]=='original body'
        assert json.loads(conn.execute('SELECT raw_json FROM messages').fetchone()[0])['sender']==BAD_ID
        result=list_contacts(conn,'acct-1')
        assert result['total']==1
        assert result['role_counts']['all']==1
        assert result['identity_quality']['quarantined']==1
        assert result['items'][0]['display_name']=='昵称🌙'
        assert set_roles(conn,[ContactKey(account_id='acct-1',contact_id=BAD_ID)],'provider',{BAD_ID:2}).failed[0].code=='contact_identity_quarantined'
        with pytest.raises(OperationError,match='contact_identity_quarantined'):
            create_operation(conn,'sync',OperationScope(account_id='acct-1',contact_id=BAD_ID),'bad-target')

def test_metadata_quarantines_payload_ids_and_keeps_unavailable_names_honest(db):
    from wechat_agent.source.repository import archive_metadata
    from wechat_agent.contacts.service import list_contacts
    people=[ContactRecord(key=ContactKey(account_id='acct-1',contact_id=BAD_ID),remark=None,nickname=None,is_self=False),
        ContactRecord(key=ContactKey(account_id='acct-1',contact_id='valid-1'),remark='bad\ufffdname',nickname='小林🧑‍💻',is_self=False),
        ContactRecord(key=ContactKey(account_id='acct-1',contact_id='valid-2'),remark=None,nickname=None,is_self=False)]
    archive_metadata(db,'acct-1',people,[])
    result=list_contacts(db,'acct-1')
    assert result['total']==2
    assert result['identity_quality']['quarantined']==1
    by_id={item['key']['contact_id']:item for item in result['items']}
    assert by_id['valid-1']['copy_name']=='小林🧑‍💻'
    assert by_id['valid-2']['copy_name'] is None
    assert by_id['valid-2']['display_name_source']=='missing'

@pytest.mark.asyncio
async def test_observed_group_member_without_friend_card_can_sync_known_group(db):
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.operations.contracts import OperationScope
    source=FakeSource();source.pages['group-1']=[make_page([make_message(sender_id='observed-person')])]
    await sync_scope(db,source,OperationScope(account_id='acct-1'),None)
    source.calls.clear()
    result=await sync_scope(db,source,OperationScope(account_id='acct-1',contact_id='observed-person'),None)
    assert result.successful_conversations==['group-1']
    assert all(call[0]=='group-1' for call in source.calls)
