"""Archive constraints protect identity and preserve original message history."""

from contextlib import closing
import sqlite3

import pytest


def test_schema_is_repeatable_and_isolated(tmp_path):
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "nested/data.sqlite")) as conn:
        migrate(conn)
        migrate(conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert 0 < conn.execute("PRAGMA busy_timeout").fetchone()[0] <= 5000
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 4
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"accounts", "contacts", "conversations", "members", "messages", "message_revisions",
                "attachments", "sync_cursors", "sync_attempts", "operations", "operation_items", "settings"} <= tables


def seed_identity(conn, account="account-a"):
    conn.execute("INSERT INTO accounts(account_id) VALUES (?)", (account,))
    conn.execute("INSERT INTO contacts(account_id, contact_id) VALUES (?, 'merchant-a')", (account,))
    conn.execute("INSERT INTO conversations(account_id, conversation_id, kind) VALUES (?, 'room', 'group')", (account,))


def insert_message(conn, account="account-a", message="message-1", sender="merchant-a", kind="text"):
    conn.execute("""INSERT INTO messages(account_id, conversation_id, message_id, sender_id,
                    sent_at, kind, body, source_revision, raw_json)
                    VALUES (?, 'room', ?, ?, '2026-11-11T10:00:00+00:00', ?, '收纳箱海运报价', 'v1', '{}')""",
                 (account, message, sender, kind))


def test_same_source_ids_are_independent_between_accounts(db):
    with db:
        seed_identity(db)
        seed_identity(db, "account-b")
        insert_message(db)
        insert_message(db, "account-b")
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError), db:
        insert_message(db)
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_foreign_keys_cannot_resolve_to_another_accounts_contact(db):
    with db:
        seed_identity(db)
        db.execute("INSERT INTO accounts(account_id) VALUES ('account-b')")
        db.execute("INSERT INTO conversations(account_id, conversation_id, kind) VALUES ('account-b', 'room', 'group')")
    with pytest.raises(sqlite3.IntegrityError), db:
        insert_message(db, "account-b")
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("INSERT INTO members(account_id, conversation_id, contact_id) VALUES ('account-b', 'room', 'merchant-a')")


def test_only_events_can_have_no_person_sender(db):
    with db:
        seed_identity(db)
        insert_message(db, message="system-1", sender=None, kind="system")
        insert_message(db, message="revoke-1", sender=None, kind="revoke")
    for sender, kind in [(None, "text"), (None, "image"), ("", "system"), ("   ", "system")]:
        with pytest.raises(sqlite3.IntegrityError), db:
            insert_message(db, message="invalid", sender=sender, kind=kind)
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_invalid_roles_and_self_as_merchant_cannot_be_saved(db):
    with db:
        seed_identity(db)
    for role, is_self in [("invalid", 0), ("merchant", 1)]:
        with pytest.raises(sqlite3.IntegrityError), db:
            db.execute("UPDATE contacts SET role=?, is_self=?", (role, is_self))
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("INSERT INTO contacts(account_id, contact_id) VALUES ('account-a', 'group@chatroom')")


def test_message_write_and_cursor_rollback_together(db):
    with db:
        seed_identity(db)
    with pytest.raises(RuntimeError), db:
        insert_message(db)
        db.execute("INSERT INTO sync_cursors(account_id, conversation_id, cursor) VALUES ('account-a', 'room', 'next')")
        raise RuntimeError("simulate interrupted archive")
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sync_cursors").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1


def test_failed_migration_does_not_leave_partial_tables(tmp_path):
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "data.sqlite")) as conn:
        conn.execute("CREATE VIEW messages AS SELECT 1")
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "messages" in names
        assert not {"schema_version", "accounts", "contacts", "conversations"} & names
        assert not conn.in_transaction


def test_newer_database_is_not_downgraded_or_modified(db):
    from wechat_agent.storage.db import migrate
    with db:
        db.execute("UPDATE schema_version SET version=999")
    with pytest.raises(RuntimeError, match="database_schema_newer_than_app"):
        migrate(db)
    assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 999


def test_migrate_refuses_to_commit_callers_transaction(db):
    from wechat_agent.storage.db import migrate
    db.execute("INSERT INTO accounts(account_id) VALUES ('uncommitted')")
    with pytest.raises(RuntimeError, match="migration_requires_idle_connection"):
        migrate(db)
    assert db.in_transaction
    db.rollback()
    assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_search_tracks_message_edits_deletes_and_rollbacks(db):
    with db:
        seed_identity(db)
        insert_message(db)
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '海运报价'").fetchone()[0] == 1
    with db:
        db.execute("UPDATE messages SET body='塑料货品备货完成'")
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '海运报价'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '备货完成'").fetchone()[0] == 1
    with pytest.raises(RuntimeError), db:
        db.execute("DELETE FROM messages")
        raise RuntimeError("rollback")
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '备货完成'").fetchone()[0] == 1
    with db:
        db.execute("DELETE FROM messages")
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '备货完成'").fetchone()[0] == 0
