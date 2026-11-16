"""Persistent sync intents, real source outcomes and honest analysis capability states."""

import asyncio
from contextlib import closing
import json
import time

import pytest

from tests.factories import make_message, make_page, seed_case
from tests.fakes.source import FakeSource
from wechat_agent.operations.contracts import OperationScope
from wechat_agent.services import Services


def scope(contact_id=None):
    return OperationScope(account_id="acct-1", contact_id=contact_id)


def test_repeated_intent_is_one_operation(db):
    from wechat_agent.operations.service import create_operation
    seed_case(db)
    first = create_operation(db, "sync_and_organize", scope("merchant-a"), "click-1")
    second = create_operation(db, "sync_and_organize", scope("merchant-a"), "click-1")
    assert first.id == second.id
    assert first.state == "queued"
    assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM operation_items").fetchone()[0] == 1


def test_idempotency_key_cannot_change_scope_or_options(db):
    from wechat_agent.operations.service import create_operation, OperationError
    from wechat_agent.operations.contracts import SyncOptions
    seed_case(db)
    create_operation(db, "sync", scope("merchant-a"), "click-1")
    with pytest.raises(OperationError, match="idempotency_key_conflict"):
        create_operation(db, "sync", scope("merchant-b"), "click-1")
    with pytest.raises(OperationError, match="idempotency_key_conflict"):
        create_operation(db, "sync", scope("merchant-a"), "click-1", options=SyncOptions(page_size=20))


def test_distinct_click_does_not_enqueue_duplicate_active_scope(db):
    from wechat_agent.operations.service import create_operation, OperationError
    create_operation(db, "sync", scope(), "click-1")
    with pytest.raises(OperationError, match="operation_already_active"):
        create_operation(db, "sync", scope(), "click-2")
    assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1


def test_operation_preserves_visible_sample_limits_without_claiming_full_history(db):
    from wechat_agent.operations.contracts import SyncOptions
    from wechat_agent.operations.service import create_operation, get_operation
    job = create_operation(db, "sync", scope(), "sample", options=SyncOptions(sample=True))
    persisted = get_operation(db, "acct-1", job.id)
    assert persisted.options.sample is True
    assert persisted.options.page_size == 20
    assert persisted.options.max_pages == 2
    assert persisted.history_complete is False


@pytest.mark.asyncio
async def test_worker_archives_source_and_reports_actual_counts(db):
    from wechat_agent.operations.service import create_operation, get_operation
    from wechat_agent.operations.worker import run_next
    operation = create_operation(db, "sync", scope(), "click-1")
    result = await run_next(db, Services(source=FakeSource()))
    assert result.id == operation.id
    assert result.state == "succeeded"
    assert result.counts["inserted"] == 4
    assert result.counts["completed_conversations"] == 2
    assert result.counts["analysis_required"] == 0
    assert result.items[0].state == "succeeded"
    assert get_operation(db, "acct-1", operation.id).remaining == 0
    assert await run_next(db, Services(source=FakeSource())) is None


@pytest.mark.asyncio
async def test_unconfigured_identity_discovery_preserves_source_success(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    create_operation(db, "sync_and_organize", scope(), "click-1")
    result = await run_next(db, Services(source=FakeSource()))
    assert result.source_state == 'succeeded' and result.state=='failed'
    assert result.report.analysis_outcome=='failed'
    assert result.counts["analysis_required"] == 0
    assert [item.phase for item in result.items] == ["source"]


@pytest.mark.asyncio
async def test_pending_merchant_analysis_is_not_fake_success_when_source_unchanged(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed_case(db)
    create_operation(db, "sync_and_organize", scope("merchant-a"), "click-1")
    result = await run_next(db, Services(source=FakeSource()))
    assert result.state == "failed"
    assert result.error_code == "capability_not_ready"
    assert result.counts["inserted"] == 0
    assert result.counts["unchanged"] == 4
    assert result.counts["analysis_required"] == 1
    assert result.counts["analysis_completed"] == 0
    assert result.remaining == 1
    assert result.available_actions == []
    assert next(item for item in result.items if item.phase == "source").state == "succeeded"
    assert [item.contact_id for item in result.items if item.phase == "analysis"] == ["merchant-a"]


@pytest.mark.asyncio
async def test_source_failure_is_failed_not_no_new_messages_and_hides_raw_errors(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    source = FakeSource()
    async def unavailable():
        raise RuntimeError("private-token and private-chat")
    source.contacts = unavailable
    create_operation(db, "sync", scope(), "click-1")
    result = await run_next(db, Services(source=source))
    assert result.state == "failed"
    assert result.error_code == "source_unavailable"
    assert "private-" not in result.model_dump_json()
    assert result.counts["inserted"] == 0
    assert result.items[0].state == "failed"


@pytest.mark.asyncio
async def test_nonmerchant_may_sync_without_analysis(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed_case(db)
    create_operation(db, "sync_and_organize", scope("provider-p"), "click-1")
    result = await run_next(db, Services(source=FakeSource()))
    assert result.state == "succeeded"
    assert result.counts["unchanged"] == 2
    assert all(item.phase != "analysis" for item in result.items)


@pytest.mark.asyncio
async def test_shared_group_updates_archive_but_only_plans_selected_merchant(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed_case(db)
    source = FakeSource()
    source.pages["group-1"] = [make_page([
        make_message(message_id="fixture:group-1:new-a", sender_id="merchant-a"),
        make_message(message_id="fixture:group-1:new-b", sender_id="merchant-b")])]
    create_operation(db, "sync_and_organize", scope("merchant-a"), "click-1")
    result = await run_next(db, Services(source=source))
    assert result.counts["inserted"] == 2
    assert db.execute("SELECT COUNT(*) FROM messages WHERE message_id LIKE '%new-%'").fetchone()[0] == 2
    assert [item.contact_id for item in result.items if item.phase == "analysis"] == ["merchant-a"]


@pytest.mark.asyncio
async def test_second_worker_cannot_claim_same_or_parallel_operation(tmp_path):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    from wechat_agent.storage.db import open_db, migrate
    source = FakeSource()
    entered, release = asyncio.Event(), asyncio.Event()
    original = source.messages
    async def slow(*args):
        entered.set()
        await release.wait()
        return await original(*args)
    source.messages = slow
    with closing(open_db(tmp_path / "queue.sqlite")) as one, closing(open_db(tmp_path / "queue.sqlite")) as two:
        migrate(one)
        seed_case(one)
        create_operation(one, "sync", scope("merchant-a"), "one")
        create_operation(one, "sync", scope("merchant-b"), "two")
        task = asyncio.create_task(run_next(one, Services(source=source)))
        await asyncio.wait_for(entered.wait(), 2)
        assert await run_next(two, Services(source=source)) is None
        release.set()
        result = await asyncio.wait_for(task, 3)
        assert result.state == "succeeded"
        assert one.execute("SELECT COUNT(*) FROM operations WHERE state='queued'").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_progress_is_durable_before_operation_finishes(db):
    from wechat_agent.operations.service import create_operation, get_operation
    from wechat_agent.operations.worker import run_next
    source = FakeSource({"group-1": [make_page(next_cursor="page:1", complete=False),
                                     make_page([make_message(message_id="fixture:group-1:2")])]})
    source.rooms = [room for room in source.rooms if room.conversation_id == "group-1"]
    original = source.messages
    async def inspect(*args):
        if args[1] is not None:
            operation = db.execute("SELECT id FROM operations").fetchone()[0]
            persisted = get_operation(db, "acct-1", operation)
            assert persisted.state == "running"
            assert persisted.counts["inserted"] == 1
            assert persisted.counts["pages_processed"] == 1
            assert not db.in_transaction
        return await original(*args)
    source.messages = inspect
    create_operation(db, "sync", scope(), "click-1")
    result = await run_next(db, Services(source=source))
    assert result.counts["inserted"] == 2


def test_queued_stop_is_persisted_and_has_no_fake_resume_action(db):
    from wechat_agent.operations.service import create_operation, control_operation
    operation = create_operation(db, "sync", scope(), "click-1")
    stopped = control_operation(db, "acct-1", operation.id, "stop")
    assert stopped.state == "stopped"
    assert stopped.generation == 2
    assert stopped.available_actions == []
    assert stopped.items[0].state == "stopped"


@pytest.mark.asyncio
async def test_stop_during_fetch_blocks_late_page_commit(db):
    from wechat_agent.operations.service import create_operation, control_operation
    from wechat_agent.operations.worker import run_next
    source = FakeSource()
    operation = create_operation(db, "sync", scope(), "click-1")
    original = source.messages
    async def stopping(*args):
        result = await original(*args)
        control_operation(db, "acct-1", operation.id, "stop")
        return result
    source.messages = stopping
    result = await run_next(db, Services(source=source))
    assert result.state == "stopped"
    assert result.counts["inserted"] == 0
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sync_cursors").fetchone()[0] == 0


def test_api_accepts_durable_queue_and_account_scoped_history(client):
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)
    client.app.state.services.source = FakeSource()
    body = {"action":"sync", "scope":{"account_id":"acct-1"}, "idempotency_key":"click-1"}
    first = client.post("/api/operations", json=body)
    assert first.status_code == 202
    assert first.json()["state"] == "queued"
    second = client.post("/api/operations", json=body)
    assert second.json()["id"] == first.json()["id"]
    target = f"/api/operations/{first.json()['id']}"
    assert client.get(target, params={"account_id":"acct-1"}).status_code == 200
    assert client.get(target, params={"account_id":"other-account"}).status_code == 403
    history = client.get("/api/operations", params={"account_id":"acct-1"}).json()
    assert history["total"] == 1
    assert history["items"][0]["id"] == first.json()["id"]
    stopped = client.post("/api/operations", json={"action":"stop", "account_id":"acct-1", "operation_id":first.json()["id"]})
    assert stopped.json()["state"] == "stopped"


def test_background_worker_completes_without_blocking_creation_and_stops_on_request(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        migrate(conn)
        seed_case(conn)
    source = FakeSource()
    original = source.messages
    async def slow(*args):
        await asyncio.sleep(0.4)
        return await original(*args)
    source.messages = slow
    with TestClient(create_app(Settings(data_dir=tmp_path), Services(source=source, auto_run=True))) as client:
        created = client.post("/api/operations", json={"action":"sync", "scope":{"account_id":"acct-1"}, "idempotency_key":"run"})
        assert created.status_code == 202
        target = f"/api/operations/{created.json()['id']}"
        deadline = time.monotonic() + 3
        while True:
            current = client.get(target, params={"account_id":"acct-1"}).json()
            if current["state"] == "running":
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        stopped = client.post("/api/operations", json={"action":"stop", "account_id":"acct-1", "operation_id":current["id"]})
        assert stopped.status_code == 200
        while True:
            current = client.get(target, params={"account_id":"acct-1"}).json()
            if current["state"] == "stopped":
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert current["counts"]["inserted"] == 0
        assert current["available_actions"] == []


def test_background_worker_finishes_source_job(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        migrate(conn)
        seed_case(conn)
    with TestClient(create_app(Settings(data_dir=tmp_path), Services(source=FakeSource(), auto_run=True))) as client:
        created = client.post("/api/operations", json={"action":"sync", "scope":{"account_id":"acct-1"}, "idempotency_key":"run"})
        target = f"/api/operations/{created.json()['id']}"
        deadline = time.monotonic() + 3
        while True:
            result = client.get(target, params={"account_id":"acct-1"}).json()
            if result["state"] in {"succeeded", "failed"}:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert result["state"] == "succeeded"
        assert result["counts"]["unchanged"] == 4


@pytest.mark.asyncio
async def test_invalid_persisted_request_fails_without_blocking_next_job(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed_case(db)
    broken = create_operation(db, "sync", scope("merchant-a"), "broken")
    create_operation(db, "sync", scope("merchant-b"), "valid")
    with db:
        db.execute("UPDATE operations SET request_json=? WHERE id=?", ('{"page_size":0}', broken.id))
    result = await run_next(db, Services(source=FakeSource()))
    assert result.state == "failed"
    assert result.error_code == "invalid_operation_request"
    assert (await run_next(db, Services(source=FakeSource()))).state == "succeeded"


def test_dead_worker_is_stopped_while_live_worker_is_left_untouched(db):
    import os
    from wechat_agent.operations.service import create_operation, get_operation
    from wechat_agent.operations.worker import recover_orphans
    seed_case(db)
    dead = create_operation(db, "sync", scope("merchant-a"), "dead")
    live = create_operation(db, "sync", scope("merchant-b"), "live")
    with db:
        db.execute("UPDATE operations SET state='running',worker_id='0:gone' WHERE id=?", (dead.id,))
        db.execute("UPDATE operations SET state='running',worker_id=? WHERE id=?", (f"{os.getpid()}:live", live.id))
    recover_orphans(db, "acct-1")
    assert get_operation(db, "acct-1", dead.id).state == "stopped"
    assert get_operation(db, "acct-1", dead.id).generation == 2
    assert get_operation(db, "acct-1", live.id).state == "running"


@pytest.mark.asyncio
async def test_unconfigured_source_does_not_silently_connect_or_succeed(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    create_operation(db, "sync", scope(), "no-source")
    result = await run_next(db, Services())
    assert result.state == "failed"
    assert result.error_code == "source_unavailable"


@pytest.mark.asyncio
async def test_page_budget_is_incomplete_and_keeps_archived_counts(db):
    from wechat_agent.operations.contracts import SyncOptions
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    source = FakeSource({"group-1": [make_page(next_cursor="page:1", complete=False)]})
    source.rooms = [room for room in source.rooms if room.conversation_id == "group-1"]
    create_operation(db, "sync", scope(), "limited", options=SyncOptions(max_pages=1))
    result = await run_next(db, Services(source=source))
    assert result.state == "failed"
    assert result.error_code == "source_incomplete"
    assert result.counts["inserted"] == 1
    assert result.counts["incomplete_conversations"] == 1
    assert db.execute("SELECT cursor FROM sync_cursors").fetchone()[0] == "page:1"


def test_control_cannot_change_scope_or_stop_foreign_operation(client):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)
        job = create_operation(conn, "sync", scope(), "bound")
    client.app.state.services.source = FakeSource()
    response = client.post("/api/operations", json={"action":"stop","account_id":"other-account","operation_id":job.id})
    assert response.status_code == 403
    response = client.post("/api/operations", json={"action":"stop","account_id":"acct-1","operation_id":job.id,
                                                   "scope":{"account_id":"other-account"}})
    assert response.status_code == 422
    assert client.get(f"/api/operations/{job.id}", params={"account_id":"acct-1"}).json()["state"] == "queued"


def test_shutdown_stops_active_operation_and_keeps_database_usable(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.operations.service import get_operation
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        migrate(conn)
        seed_case(conn)
    source = FakeSource()
    async def waiting(*args):
        await asyncio.Event().wait()
    source.messages = waiting
    with TestClient(create_app(Settings(data_dir=tmp_path), Services(source=source))) as client:
        created = client.post("/api/operations", json={"action":"sync","scope":{"account_id":"acct-1"},"idempotency_key":"shutdown"})
        job_id = created.json()["id"]
        deadline = time.monotonic() + 3
        while client.get(f"/api/operations/{job_id}", params={"account_id":"acct-1"}).json()["state"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.01)
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        result = get_operation(conn, "acct-1", job_id)
        assert result.state == "stopped"
        assert result.error_code == "operation_interrupted"
        assert conn.execute("SELECT COUNT(*) FROM sync_leases").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_directory_only_unknown_contacts_do_not_require_a_model(db):
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    source=FakeSource()
    source.pages={room.conversation_id:[make_page([],conversation_id=room.conversation_id,conversation_kind=room.kind)] for room in source.rooms}
    create_operation(db,'sync_and_organize',scope(),'directory-only')
    result=await run_next(db,Services(source=source))
    assert result.state=='succeeded' and result.source_state=='succeeded'
    assert result.report.analysis_outcome=='not_applicable'
    assert not result.report.contacts
