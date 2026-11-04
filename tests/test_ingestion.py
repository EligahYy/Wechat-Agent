import sqlite3

import pytest

from wechat_agent.db import DB
from wechat_agent.ingestion import ingest


def test_atomic_validation_and_preview(db, chat, record):
    assert ingest(db, [record], True)["inserted"] == 1
    assert not db.rows("SELECT * FROM messages")
    with pytest.raises(ValueError):
        ingest(db, [record, record | {"event_time": "2026-11-04T09:00:00"}])
    assert not db.rows("SELECT * FROM messages")


def test_same_second_duplicate_and_revision(db, chat, record):
    assert ingest(db, [record, record | {"source_id": "2"}])["inserted"] == 2
    assert ingest(db, [record])["duplicates"] == 1
    assert ingest(db, [record | {"text": "已改期"}])["revised"] == 1
    assert len(db.rows("SELECT * FROM messages")) == 2
    assert len(db.rows("SELECT * FROM message_revisions")) == 1
    assert (
        len(db.rows("SELECT * FROM jobs")) == 2
    )  # two distinct input snapshots, no empty policy job


def test_non_allowlisted_content_never_saved(db, record):
    assert ingest(db, [record])["excluded"] == 1
    assert not db.rows("SELECT * FROM messages")


def test_backup_restores_relationships(db, chat, record, tmp_path):
    ingest(db, [record])
    target = tmp_path / "backup.sqlite3"
    db.backup(target)
    c = sqlite3.connect(target)
    assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.close()
    assert DB(db.settings).rows("SELECT * FROM conversations")[0]["id"] == chat
