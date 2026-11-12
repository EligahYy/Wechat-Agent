"""Names retain provenance; unreadable fields must not erase known values."""
from datetime import datetime, timezone

import pytest

from tests.factories import make_page, make_message
from wechat_agent.contacts.service import list_contacts
from wechat_agent.source.contracts import ContactKey, ContactRecord, ConversationRecord
from wechat_agent.source.repository import archive_metadata, archive_page


def person(remark='真实备注', nickname='昵称', **states):
    return ContactRecord(key=ContactKey(account_id='acct-1', contact_id='person-a'),
                         remark=remark, nickname=nickname, is_self=False, **states)


def group_name(value='群内甲', room='group-1', **extra):
    from wechat_agent.source.contracts import NameEvidence
    return NameEvidence(contact_id='person-a', origin='group_member', conversation_id=room,
                        value=value, state='known', **extra)


def room_with_name(value='群内甲', room='group-1'):
    return ConversationRecord(account_id='acct-1', conversation_id=room, kind='group',
                              title='群聊', member_ids=['person-a'], membership_state='known',
                              name_evidence=[group_name(value, room)])


def test_unreadable_fields_preserve_last_good_name_without_claiming_it_current(db):
    archive_metadata(db, 'acct-1', [person()], [])
    archive_metadata(db, 'acct-1', [person(None, None, remark_state='unreadable', nickname_state='unreadable')], [])
    raw = db.execute("SELECT remark,nickname FROM contacts WHERE contact_id='person-a'").fetchone()
    assert tuple(raw) == ('真实备注', '昵称')
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name'] == '真实备注'
    assert item['name_status'] == 'last_known'
    assert item['name_reason'] == 'name_read_failed'
    assert item['copy_name'] is None


def test_explicit_empty_clears_name_but_not_identity_or_original_messages(db):
    archive_metadata(db, 'acct-1', [person()], [])
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    with db:
        db.execute("UPDATE contacts SET role='merchant',role_version=3 WHERE contact_id='person-a'")
    archive_metadata(db, 'acct-1', [person(None, None, remark_state='empty', nickname_state='empty')], [])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name_source'] == 'missing'
    assert item['role'] == 'merchant' and item['role_version'] == 3
    assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_group_name_enriches_observed_person_but_is_not_a_global_copy_name(db):
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    archive_metadata(db, 'acct-1', [], [room_with_name()])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name'] == '群内甲'
    assert item['display_name_source'] == 'group_member'
    assert item['name_status'] == 'scoped'
    assert item['name_scope'] == 'group-1'
    assert item['copy_name'] is None
    assert list_contacts(db, 'acct-1', q='群内甲')['total'] == 1


def test_multiple_group_names_keep_scopes_and_expose_conflict(db):
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    archive_metadata(db, 'acct-1', [], [room_with_name('群内甲'), room_with_name('群内乙', 'group-2')])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['name_conflict'] is True
    assert item['copy_name'] is None
    assert db.execute("SELECT COUNT(DISTINCT conversation_id) FROM contact_names WHERE contact_id='person-a'").fetchone()[0] == 2


def test_current_global_name_has_priority_over_room_name(db):
    archive_metadata(db, 'acct-1', [person()], [room_with_name()])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name'] == '真实备注'
    assert item['copy_name'] == '真实备注'
    assert item['name_status'] == 'current'


def test_new_scoped_name_has_priority_over_a_contact_absent_from_current_metadata(db):
    archive_metadata(db, 'acct-1', [person()], [])
    archive_metadata(db, 'acct-1', [], [room_with_name()])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name'] == '群内甲'
    assert item['metadata_current'] is False


def test_complete_group_roster_does_not_create_every_unobserved_member_as_a_contact(db):
    archive_metadata(db, 'acct-1', [], [room_with_name()])
    assert list_contacts(db, 'acct-1')['total'] == 0
    assert db.execute('SELECT COUNT(*) FROM source_group_members').fetchone()[0] == 1
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    assert list_contacts(db, 'acct-1')['items'][0]['display_name'] == '群内甲'


def test_unknown_legacy_empty_is_not_treated_as_verified_user_deletion(db):
    archive_metadata(db, 'acct-1', [person()], [])
    archive_metadata(db, 'acct-1', [person(None, None, remark_state='unknown', nickname_state='unknown')], [])
    assert db.execute("SELECT remark FROM contacts WHERE contact_id='person-a'").fetchone()[0] == '真实备注'
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['name_status'] == 'last_known'
    assert item['copy_name'] is None


def test_metadata_observation_is_persisted_without_resetting_roles(db):
    archive_metadata(db, 'acct-1', [person()], [], metadata={
        'mode': 'sqlcipher', 'generation': 2, 'resolver_generation': 2,
        'refreshed_at': '2026-11-12T00:00:00Z', 'patch_id': 'wechat-agent.1',
    })
    row = db.execute("SELECT source_mode,generation FROM source_metadata_status WHERE account_id='acct-1'").fetchone()
    assert tuple(row) == ('sqlcipher', 2)


def test_unreadable_group_roster_retains_name_as_last_known(db):
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    archive_metadata(db, 'acct-1', [], [room_with_name()])
    unreadable = ConversationRecord(account_id='acct-1', conversation_id='group-1',kind='group',
                                    title='群聊',membership_state='unreadable')
    archive_metadata(db, 'acct-1', [], [unreadable])
    item = list_contacts(db, 'acct-1')['items'][0]
    assert item['display_name'] == '群内甲'
    assert item['name_status'] == 'last_known' and item['name_reason'] == 'name_read_failed'
    assert item['copy_name'] is None


def test_quality_counts_follow_effective_scoped_names(db):
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    archive_metadata(db, 'acct-1', [], [room_with_name()])
    quality = list_contacts(db, 'acct-1')['identity_quality']
    assert quality['names_unavailable'] == 0
    assert quality['names_scoped'] == 1


def test_revalidated_metadata_rejects_a_forged_evidence_scope_without_changes(db):
    from wechat_agent.source.adapter import SourceError
    archive_metadata(db, 'acct-1', [person()], [])
    valid = room_with_name()
    forged = valid.model_copy(update={'name_evidence':[group_name(room='wrong-room')]})
    with pytest.raises(SourceError, match='source_metadata_contract_invalid'):
        archive_metadata(db, 'acct-1', [], [forged])
    assert list_contacts(db, 'acct-1')['items'][0]['copy_name'] == '真实备注'


def test_schema4_upgrade_failure_is_atomic(tmp_path, monkeypatch):
    from contextlib import closing
    from wechat_agent.storage import db as storage
    with closing(storage.open_db(tmp_path/'old.sqlite3')) as conn:
        with monkeypatch.context() as older:
            older.setattr(storage, 'SCHEMA_VERSION', 4)
            older.setattr(storage, '_MIGRATIONS', storage._MIGRATIONS[:4])
            storage.migrate(conn)
        conn.execute('CREATE VIEW contact_names AS SELECT 1')
        conn.commit()
        import sqlite3
        with pytest.raises(sqlite3.OperationalError): storage.migrate(conn)
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0] == 4
        assert 'metadata_current' not in {row[1] for row in conn.execute('PRAGMA table_info(contacts)')}


def test_source_title_presentation_preserves_raw_title_and_does_not_claim_messages(db):
    room = ConversationRecord(account_id='acct-1',conversation_id='group-1',kind='group',
        title='家居讨论群 (group-1)',member_ids=['person-a'],origin='session')
    archive_metadata(db,'acct-1',[person()],[room])
    source = list_contacts(db,'acct-1')['items'][0]['sources'][0]
    assert source['title'] == '家居讨论群'
    assert source['provenance'] == 'session'
    assert source['has_messages'] is False
    assert db.execute("SELECT title FROM conversations WHERE conversation_id='group-1'").fetchone()[0] == '家居讨论群 (group-1)'


def test_candidate_recency_uses_instants_not_timezone_text(db):
    from datetime import datetime
    archive_page(db, make_page([make_message(sender_id='person-a')]))
    older = group_name('较早名称', 'group-1', observed_at=datetime.fromisoformat('2026-11-12T08:00:00+08:00'))
    newer = group_name('较新名称', 'group-2', observed_at=datetime.fromisoformat('2026-11-12T01:00:00+00:00'))
    rooms = [ConversationRecord(account_id='acct-1',conversation_id=name.conversation_id,
        kind='group',title=None,name_evidence=[name]) for name in (older,newer)]
    archive_metadata(db,'acct-1',[],rooms)
    assert list_contacts(db,'acct-1')['items'][0]['display_name'] == '较新名称'
