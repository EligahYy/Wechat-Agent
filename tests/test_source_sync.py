"""Durable source pages, revisions, attribution gaps and interrupted syncs."""

import asyncio
from contextlib import closing
import json
import sqlite3

import pytest

from tests.factories import make_message, make_page


def test_replay_page_is_idempotent_and_identical_bodies_keep_distinct_ids(db, case):
    from wechat_agent.source.contracts import SourcePage
    from wechat_agent.source.repository import archive_page
    page = SourcePage.model_validate(case("source-overlap")["page"])
    first = archive_page(db, page)
    second = archive_page(db, page)
    assert (first.inserted, first.revised, first.unchanged) == (2, 0, 0)
    assert (second.inserted, second.revised, second.unchanged) == (0, 0, 2)
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM message_revisions").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(DISTINCT body) FROM messages").fetchone()[0] == 1


def test_revisions_keep_original_time_raw_and_current_search(db):
    from wechat_agent.source.repository import archive_page
    first = make_message(body="原始海运报价", raw={"content": "first"})
    second = make_message(body="新的备货要求", raw={"content": "second"}, source_revision="source-v2")
    archive_page(db, make_page([first]))
    assert archive_page(db, make_page([second])).revised == 1
    rows = db.execute("SELECT revision,body,raw_json,sent_at FROM message_revisions ORDER BY revision").fetchall()
    assert [(r["revision"], r["body"]) for r in rows] == [(1, "原始海运报价"), (2, "新的备货要求")]
    assert json.loads(rows[0]["raw_json"]) == {"content": "first"}
    assert rows[0]["sent_at"] == "2026-11-11T18:00:00+08:00"
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '海运报价'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM message_search WHERE message_search MATCH '备货要求'").fetchone()[0] == 1


def test_failed_commit_cannot_advance_cursor_or_leave_partial_messages(tmp_path):
    from wechat_agent.storage.db import migrate
    from wechat_agent.source.repository import archive_page
    class FailCommit(sqlite3.Connection):
        fail = False
        def commit(self):
            if self.fail:
                raise sqlite3.OperationalError("synthetic commit failure")
            super().commit()
    with closing(sqlite3.connect(tmp_path / "test.sqlite", factory=FailCommit)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        migrate(conn)
        conn.fail = True
        with pytest.raises(sqlite3.OperationalError):
            archive_page(conn, make_page(next_cursor="page:1", complete=False))
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sync_cursors").fetchone()[0] == 0
        assert not conn.in_transaction


def test_message_identity_cannot_be_reassigned_to_another_conversation(db):
    from wechat_agent.source.repository import archive_page
    from wechat_agent.source.adapter import SourceError
    archive_page(db, make_page())
    other = make_message(conversation_id="other-room")
    with pytest.raises(SourceError, match="source_message_identity_conflict"):
        archive_page(db, make_page([other], conversation_id="other-room"))
    assert db.execute("SELECT conversation_id FROM messages").fetchone()[0] == "group-1"


def test_empty_page_can_persist_a_scoped_cursor_without_becoming_complete(db):
    from wechat_agent.source.repository import archive_page
    archive_page(db, make_page([], next_cursor="page:1", complete=False))
    row = db.execute("SELECT conversation_id,cursor,complete FROM sync_cursors").fetchone()
    assert tuple(row) == ("group-1", "page:1", 0)


def test_metadata_refresh_does_not_overwrite_manual_roles(db, case):
    from tests.factories import seed_case
    from tests.fakes.source import FakeSource
    from wechat_agent.source.repository import archive_metadata
    seed_case(db)
    source = FakeSource()
    source.people[0] = source.people[0].model_copy(update={"remark": "Renamed"})
    archive_metadata(db, source.account_id, source.people, source.rooms)
    row = db.execute("SELECT remark,role,role_version FROM contacts WHERE contact_id='merchant-a'").fetchone()
    assert tuple(row) == ("Renamed", "merchant", 1)
    assert db.execute("SELECT COUNT(*) FROM contacts WHERE contact_id IN ('group-1','dm-a')").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM contacts WHERE is_self=0").fetchone()[0] == 28


@pytest.mark.asyncio
async def test_sync_completed_scope_replays_without_duplicate_records(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.sync import sync_scope
    source = FakeSource()
    first = await sync_scope(db, source, OperationScope(account_id=source.account_id), None)
    second = await sync_scope(db, source, OperationScope(account_id=source.account_id), None)
    assert first.inserted == 4
    assert second.inserted == second.revised == 0
    assert second.unchanged == 4
    assert sorted(second.successful_conversations) == ["dm-a", "group-1"]
    assert second.gaps == []
    assert second.history_complete is False
    assert db.execute("SELECT COUNT(*) FROM message_revisions").fetchone()[0] == 4


@pytest.mark.asyncio
async def test_sync_fetches_outside_transactions_and_resumes_page_limit(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.sync import sync_scope
    pages = [make_page(next_cursor="page:1", complete=False),
             make_page([make_message(message_id="fixture:group-1:2")])]
    source = FakeSource({"group-1": pages})
    original = source.messages
    async def messages(*args):
        assert not db.in_transaction
        return await original(*args)
    source.messages = messages
    scope = OperationScope(account_id=source.account_id)
    first = await sync_scope(db, source, scope, None, conversation_ids=["group-1"], max_pages=1)
    assert "source_page_limit_reached" in first.gaps
    assert db.execute("SELECT cursor FROM sync_cursors").fetchone()[0] == "page:1"
    second = await sync_scope(db, source, scope, None, conversation_ids=["group-1"])
    assert second.inserted == 1
    assert source.calls[-1][1] == "page:1"
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_nonprogressing_cursor_stops_without_spinning(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.sync import sync_scope
    pages = [make_page(next_cursor="page:1", complete=False),
             make_page([make_message(message_id="fixture:group-1:2")], next_cursor="page:1", complete=False)]
    source = FakeSource({"group-1": pages})
    result = await sync_scope(db, source, OperationScope(account_id=source.account_id), None,
                              conversation_ids=["group-1"])
    assert "source_cursor_no_progress" in result.gaps
    assert len(source.calls) == 2
    assert result.successful_conversations == []


@pytest.mark.asyncio
async def test_source_error_is_failed_sync_not_no_new_messages(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.adapter import SourceError
    from wechat_agent.source.sync import sync_scope
    source = FakeSource()
    async def unavailable(*args):
        raise SourceError("source_unreachable")
    source.messages = unavailable
    result = await sync_scope(db, source, OperationScope(account_id=source.account_id), None,
                              conversation_ids=["group-1"])
    assert result.successful_conversations == []
    assert result.failed_conversations == ["group-1"]
    assert result.gaps == ["source_unreachable"]
    assert db.execute("SELECT state FROM sync_attempts").fetchone()[0] == "failed"


@pytest.mark.asyncio
async def test_same_conversation_syncs_serialize_across_connections(tmp_path):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.storage.db import open_db, migrate
    source = FakeSource()
    entered = asyncio.Event()
    release = asyncio.Event()
    original = source.messages
    active = 0
    async def slow_messages(*args):
        nonlocal active
        active += 1
        assert active == 1
        entered.set()
        await release.wait()
        try:
            return await original(*args)
        finally:
            active -= 1
    source.messages = slow_messages
    scope = OperationScope(account_id=source.account_id)
    with closing(open_db(tmp_path / "archive.sqlite3")) as one, closing(open_db(tmp_path / "archive.sqlite3")) as two:
        migrate(one)
        first = asyncio.create_task(sync_scope(one, source, scope, None, conversation_ids=["group-1"]))
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(sync_scope(two, source, scope, None, conversation_ids=["group-1"]))
        await asyncio.sleep(0.05)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 3)
        assert sum(row.inserted for row in results) == 2
        assert sum(row.unchanged for row in results) == 2
        assert one.execute("SELECT COUNT(*) FROM sync_leases").fetchone()[0] == 0


def test_archive_revalidates_scope_even_if_caller_mutated_model(db):
    from wechat_agent.source.adapter import SourceError
    from wechat_agent.source.repository import archive_page
    page = make_page().model_copy(update={"records": [make_message(account_id="another-account")]})
    with pytest.raises(SourceError, match="source_message_contract_invalid"):
        archive_page(db, page)
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_repeated_final_page_cannot_be_reported_complete(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.sync import sync_scope
    source = FakeSource({"group-1": [make_page(next_cursor="page:1", complete=False), make_page()]})
    result = await sync_scope(db, source, OperationScope(account_id=source.account_id), None,
                              conversation_ids=["group-1"])
    assert "source_page_no_progress" in result.gaps
    assert result.successful_conversations == []
    assert db.execute("SELECT complete FROM sync_cursors").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_stop_during_fetch_does_not_commit_page_or_advance_cursor(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope, CancellationToken
    from wechat_agent.source.repository import archive_metadata
    from wechat_agent.source.sync import sync_scope
    source = FakeSource()
    archive_metadata(db, source.account_id, source.people, source.rooms)
    with db:
        db.execute("""INSERT INTO operations(account_id,id,action,idempotency_key,state)
                      VALUES ('acct-1','op-1','sync','key-1','running')""")
    original = source.messages
    async def stopping(*args):
        page = await original(*args)
        with db:
            db.execute("UPDATE operations SET state='stop_requested' WHERE id='op-1'")
        return page
    source.messages = stopping
    result = await sync_scope(db, source, OperationScope(account_id=source.account_id),
                              CancellationToken(operation_id="op-1", generation=1), conversation_ids=["group-1"])
    assert result.stopped
    assert result.gaps == ["source_sync_stopped"]
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sync_cursors").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sync_leases").fetchone()[0] == 0


def test_version_one_database_upgrades_without_losing_originals(tmp_path):
    from importlib.resources import files
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "old.sqlite")) as conn:
        conn.executescript(files("wechat_agent.storage").joinpath("migrations/001_archive.sql").read_text())
        with conn:
            conn.execute("CREATE TABLE schema_version(singleton INTEGER PRIMARY KEY,version INTEGER NOT NULL)")
            conn.execute("INSERT INTO schema_version VALUES (1,1)")
            conn.execute("INSERT INTO accounts(account_id) VALUES ('original-account')")
        migrate(conn)
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 20
        assert conn.execute("SELECT account_id FROM accounts").fetchone()[0] == "original-account"
        assert conn.execute("SELECT COUNT(*) FROM source_issues").fetchone()[0] == 0


def test_attachment_links_and_existing_file_state_survive_replay(db):
    from wechat_agent.source.repository import archive_page
    record = make_message(kind="image", attachment_ids=["media:fixture:group-1:1"],
                          raw={"content": {"Image": {"md5": "synthetic"}}})
    page = make_page([record])
    archive_page(db, page)
    with db:
        db.execute("UPDATE attachments SET state='original',local_path='private-image.png'")
    assert archive_page(db, page).unchanged == 1
    attachment = db.execute("SELECT state,local_path FROM attachments").fetchone()
    assert tuple(attachment) == ("original", "private-image.png")
    assert json.loads(db.execute("SELECT raw_json FROM message_revisions").fetchone()[0]) == record.raw


@pytest.mark.asyncio
async def test_missing_message_id_restarts_only_affected_cursor_and_keeps_reading_other_rooms(db):
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.source.contracts import SourceIssue
    from wechat_agent.source.coverage import assess_sync
    from wechat_agent.source.sync import sync_scope

    source = FakeSource()
    saved_group = source.pages['group-1'][0]
    first = make_page(conversation_id='dm-a', conversation_kind='private', records=[
        make_message(conversation_id='dm-a', message_id='dm-a:stable'),
    ], next_cursor='page:1', complete=False)
    issue = SourceIssue(code='source_message_id_unavailable', raw={'talker':'dm-a','server_id':0})
    broken = make_page([], conversation_id='dm-a', conversation_kind='private', next_cursor='page:2', complete=False).model_copy(
        update={'issues':[issue], 'gaps':[issue.code]})
    later = make_page([make_message(conversation_id='dm-a', message_id='dm-a:later')],
                      conversation_id='dm-a', conversation_kind='private')
    source.pages = {'dm-a': [first, broken, later], 'group-1': [saved_group]}
    scope = OperationScope(account_id=source.account_id)

    failed = await sync_scope(db, source, scope, None)
    assert failed.failed_conversations == ['dm-a']
    assert ('dm-a', 'page:2', 200) in source.calls
    assert tuple(db.execute("SELECT cursor,complete FROM sync_cursors WHERE conversation_id='dm-a'").fetchone()) == ('page:1', 0)
    assert db.execute("SELECT COUNT(*) FROM messages WHERE message_id='dm-a:later'").fetchone()[0] == 1
    assert failed.successful_conversations == ['group-1']
    assert not assess_sync(db, source.account_id, {'merchant-a'}, failed).global_blocked

    source.calls.clear()
    retry = await sync_scope(db, source, scope, None)
    assert source.calls[0][:2] == ('dm-a', None)
    assert retry.failed_conversations == ['dm-a']
    assert retry.successful_conversations == ['group-1']
    assert db.execute("SELECT COUNT(*) FROM messages WHERE message_id='dm-a:stable'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM source_issues WHERE resolved=0").fetchone()[0] > 0
