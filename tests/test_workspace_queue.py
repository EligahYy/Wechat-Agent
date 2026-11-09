import json

import httpx
import pytest
from model_packets import packet_response
from test_workspace import proposal

from wechat_agent.crm import configure as authorize
from wechat_agent.db import dumps, now
from wechat_agent.ingestion import ingest
from wechat_agent.workspace import queue
from wechat_agent.workspace.store import read
from wechat_agent.workspace.views import details


@pytest.fixture
def ready(db, chat, record, monkeypatch):
    db.settings.bind_source("account")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    authorize(db, True)
    ingest(
        db, [record | {"sender_id": "merchant", "text": "下周英国3方货，请确认报价"}]
    )
    with db.tx() as c:
        c.execute(
            "INSERT INTO identity_metadata VALUES('account','merchant','张先生','张','',?)",
            (now(),),
        )
    return db


def model(db, callback=None):
    def respond(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        if callback:
            response = callback(data)
            if response is not None:
                return response
        packet = packet_response(request)
        if packet is not None:
            return packet
        _, p = proposal(db)
        result = {"proposal": p.model_dump()}
        if "draft" in data:
            result["checked"] = True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": dumps(result)}}
                ],
                "usage": {"total_tokens": 1},
            },
        )

    return httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    )


def test_queue_off_until_enabled_then_reuses_complete_result(ready):
    db = ready
    with model(db) as client:
        assert not queue.step(db, client=client)
        assert not db.rows("SELECT * FROM usage")
        queue.configure(db, True)
        assert queue.step(db, client=client)
        assert queue.report(db)["counts"] == {"succeeded": 1}
        calls = len(db.rows("SELECT * FROM usage"))
        assert not queue.step(db, client=client)
        assert len(db.rows("SELECT * FROM usage")) == calls
    assert read(db, "merchant")["body"]["coverage"]["processed_messages"] == 1


def test_append_during_analysis_publishes_pinned_history_and_requeues(ready, record):
    db = ready
    added = []

    def append(payload):
        if payload.get("phase") == "extract" and not added:
            added.append(True)
            ingest(
                db,
                [
                    record
                    | {
                        "source_id": "new-append",
                        "sender_id": "merchant",
                        "event_time": "2026-11-09T16:00:00+08:00",
                        "text": "新补充的下一批需求",
                    }
                ],
            )

    queue.configure(db, True)
    with model(db, append) as client:
        assert queue.step(db, client=client)
        assert read(db, "merchant")["body"]["coverage"]["processed_messages"] == 1
        assert details(db, "merchant")["needs_update"]
        assert queue.report(db)["counts"] == {"queued": 1}
        with db.tx() as c:
            c.execute("UPDATE workspace_queue SET available_at=?", (now(),))
        assert queue.step(db, client=client)
    assert not details(db, "merchant")["needs_update"]
    assert read(db, "merchant")["body"]["coverage"]["processed_messages"] == 2


def test_revision_edit_during_request_still_blocks_publication(ready):
    db = ready

    def edit(payload):
        if payload.get("phase") == "extract":
            with db.tx() as c:
                c.execute("UPDATE messages SET revision=revision+1")

    queue.configure(db, True)
    with model(db, edit) as client:
        assert queue.step(db, client=client)
    assert not read(db, "merchant")
    assert queue.report(db)["counts"] == {"queued": 1}
    assert len(db.rows("SELECT * FROM usage")) == 1


def test_pause_during_final_review_prevents_publication(ready):
    db = ready

    def pause(payload):
        if "draft" in payload:
            queue.configure(db, False)

    queue.configure(db, True)
    with model(db, pause) as client:
        assert queue.step(db, client=client)
        calls = len(db.rows("SELECT * FROM usage"))
        assert not queue.step(db, client=client)
        assert len(db.rows("SELECT * FROM usage")) == calls
    assert not read(db, "merchant")
    assert not queue.report(db)["enabled"]


def test_auth_failure_stops_account_until_explicit_resume(ready):
    db = ready
    called = []

    def rejected(payload):
        called.append(1)
        return httpx.Response(401)

    queue.configure(db, True)
    with model(db, rejected) as client:
        assert queue.step(db, client=client)
        assert queue.report(db)["gate"] == "HTTP_401"
        assert not queue.step(db, client=client)
    assert len(called) == 1
    queue.configure(db, True)
    with model(db) as client:
        assert queue.step(db, client=client)
    assert queue.report(db)["gate"] is None


def test_budget_change_wakes_paused_history_without_clearing_usage(ready):
    db = ready
    authorize(db, True, budget=1000)
    queue.configure(db, True)
    with model(db) as client:
        assert queue.step(db, client=client)
        assert queue.report(db)["counts"] == {"paused": 1}
        assert queue.report(db)["gate"] == "blocked_budget"
        assert not db.rows("SELECT * FROM usage")
        authorize(db, True, budget=100000)
        assert queue.step(db, client=client)
    assert queue.report(db)["counts"] == {"succeeded": 1}
    assert len(db.rows("SELECT * FROM usage")) == 3


def test_retry_failures_back_off_and_stop_after_three_attempts(ready):
    db = ready
    queue.configure(db, True)

    def network(payload):
        raise httpx.ConnectError("synthetic refused")

    with model(db, network) as client:
        for n in range(3):
            assert queue.step(db, client=client)
            assert not queue.step(db, client=client)
            with db.tx() as c:
                c.execute(
                    "UPDATE workspace_automation SET gate_until='2000-01-01T00:00:00+00:00'"
                )
                c.execute("UPDATE workspace_queue SET available_at=?", (now(),))
    assert queue.report(db)["counts"] == {"failed": 1}
    assert all(
        r["status"] == "request_rejected" for r in db.rows("SELECT * FROM usage")
    )


def test_contact_excluded_before_queue_run_is_not_analyzed(ready):
    db = ready
    queue.configure(db, True)
    with db.tx() as c:
        c.execute("INSERT INTO actor_exclusions VALUES('account','merchant','同事')")
    with model(db) as client:
        assert not queue.step(db, client=client)
    assert not db.rows("SELECT * FROM usage")
    assert queue.report(db)["total"] == 0


def test_global_queue_lock_prevents_reentrant_worker(ready):
    db = ready
    queue.configure(db, True)

    def nested(payload):
        assert not queue.step(db)

    with model(db, nested) as client:
        assert queue.step(db, client=client)
    assert queue.report(db)["counts"] == {"succeeded": 1}


def test_runtime_default_never_starts_legacy_worker(ready, monkeypatch):
    from wechat_agent import runtime

    worker = runtime.Runtime(ready)

    def forbidden(*args):
        raise AssertionError("legacy worker must not execute")

    def step(db, **kwargs):
        worker.stop.set()
        return False

    monkeypatch.setattr(runtime, "schedule", forbidden)
    monkeypatch.setattr(runtime, "run_once", forbidden)
    monkeypatch.setattr(queue, "step", step)
    worker.analyze()
    assert ready.settings.analysis_mode == "workspace"


def test_queue_api_auth_and_home_is_customer_workspace(ready):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    c = TestClient(create_app(ready.settings))
    assert c.get("/api/workspace/queue").status_code == 401
    h = {"Authorization": "Bearer " + ready.token}
    assert "完整客户资料与今日行动" in c.get("/", headers=h).text
    assert 'type="module"' in c.get("/?page=settings", headers=h).text
    assert (
        c.post(
            "/api/workspace/automation", headers=h, json={"enabled": True}
        ).status_code
        == 200
    )
    assert c.get("/api/workspace/queue", headers=h).json()["total"] == 1
    assert (
        c.post(
            "/api/workspace/automation", headers=h, json={"enabled": "yes"}
        ).status_code
        == 422
    )
    assert c.get("/api/workspace/queue?page=0", headers=h).status_code == 422


def test_call_limit_continues_automatically_using_saved_packets(ready, monkeypatch):
    from wechat_agent.workspace import agent
    from wechat_agent.workspace.transport import ModelSession

    db = ready
    queue.configure(db, True)
    monkeypatch.setattr(
        agent, "ModelSession", lambda *args: ModelSession(*args, limit=2)
    )
    with model(db) as client:
        assert queue.step(db, client=client)
        assert queue.report(db)["counts"] == {"paused": 1}
        assert not read(db, "merchant")
        with db.tx() as c:
            c.execute("UPDATE workspace_queue SET available_at=?", (now(),))
        assert queue.step(db, client=client)
    assert queue.report(db)["counts"] == {"succeeded": 1}
    assert len(db.rows("SELECT * FROM usage")) == 3
    assert len(db.rows("SELECT * FROM workspace_packets WHERE kind='extract'")) == 1


def test_recent_contact_priority_preserves_historical_queue(ready, record):
    from wechat_agent.services import allow_conversation

    db = ready
    allow_conversation(
        db,
        "fixture",
        "account",
        "older",
        "历史商家",
        "private",
        None,
        None,
        True,
        followup_source=True,
    )
    ingest(
        db,
        [
            record
            | {
                "conversation_id": "older",
                "conversation_type": "private",
                "sender_id": "older",
                "source_id": "old1",
                "event_time": "2025-01-01T00:00:00+00:00",
            }
        ],
    )
    queue.configure(db, True)
    rows = {r["source_id"]: r for r in db.rows("SELECT * FROM workspace_queue")}
    assert rows["merchant"]["priority"] == 0
    assert rows["older"]["priority"] == 1
    assert rows["older"]["status"] == "queued"
    assert queue.report(db)["total"] == 2


def test_manual_decision_during_request_wins_over_automatic_update(ready, record):
    from wechat_agent.workspace.context import snapshot
    from wechat_agent.workspace.store import command, commit

    db = ready
    ctx, p = proposal(db)
    initial = commit(db, "merchant", p, ctx, snapshot(db, "merchant"))
    ingest(
        db,
        [
            record
            | {
                "source_id": "later",
                "sender_id": "merchant",
                "event_time": "2026-11-09T10:00:00+00:00",
                "text": "报价需要更新",
            }
        ],
    )
    paused = []

    def intervene(payload):
        if "draft" in payload and not paused:
            paused.append(True)
            command(db, "merchant", initial["version"], "pause", value=True)

    queue.configure(db, True)
    with model(db, intervene) as client:
        assert queue.step(db, client=client)
    doc = read(db, "merchant")
    assert doc["version"] == initial["version"] + 1
    assert doc["body"]["paused"]
    assert queue.report(db)["counts"] == {"queued": 1}


def test_v12_upgrade_preserves_v11_and_creates_backup(ready):
    import sqlite3

    from wechat_agent.db import DB

    db = ready
    with db.tx() as c:
        c.execute("DROP TABLE workspace_queue")
        c.execute("DROP TABLE workspace_automation")
        c.execute("PRAGMA user_version=11")
    DB(db.settings)
    path = list(db.settings.data_dir.glob("pre-v12-*.sqlite3"))[-1]
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 11
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert not queue.settings(db)["enabled"]


def test_resuming_customer_is_completed_before_opening_more_histories(
    ready, record, monkeypatch
):
    from wechat_agent.services import allow_conversation

    db = ready
    allow_conversation(
        db,
        "fixture",
        "account",
        "second",
        "另一位",
        "private",
        None,
        None,
        True,
        followup_source=True,
    )
    ingest(
        db,
        [
            record
            | {
                "conversation_id": "second",
                "conversation_type": "private",
                "source_id": "p1",
                "sender_id": "second",
            }
        ],
    )
    queue.configure(db, True)
    calls = []

    def paused(db, source_id, client, should_stop=None):
        calls.append(source_id)
        return {"paused": True, "reason": "call_limit"}

    monkeypatch.setattr(queue, "run", paused)
    assert queue.step(db)
    first = calls[0]
    with db.tx() as c:
        c.execute(
            "UPDATE workspace_queue SET available_at=? WHERE source_id=?",
            (now(), first),
        )
    assert queue.step(db, refresh=False)
    assert calls == [first, first]
    assert queue.report(db)["total"] == 2


def test_explicit_retry_refreshes_invalid_responses_but_reuses_fact_packets(ready):
    db = ready
    queue.configure(db, True)

    def invalid_summary(payload):
        if payload.get("phase") == "synthesize":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "invalid JSON"},
                        }
                    ],
                    "usage": {"total_tokens": 1},
                },
            )

    with model(db, invalid_summary) as client:
        assert queue.step(db, client=client)
    assert queue.report(db)["counts"] == {"failed": 1}
    assert len(db.rows("SELECT * FROM workspace_packets")) == 1
    usage = len(db.rows("SELECT * FROM usage"))
    queue.retry(db, "merchant")
    with model(db) as client:
        assert queue.step(db, client=client)
    assert queue.report(db)["counts"] == {"succeeded": 1}
    assert len(db.rows("SELECT * FROM workspace_packets")) == 1
    assert len(db.rows("SELECT * FROM usage")) == usage + 2


def test_application_background_processes_queue_after_user_enables_it(
    ready, monkeypatch
):
    import time

    from fastapi.testclient import TestClient

    from wechat_agent.runtime import Runtime
    from wechat_agent.web import create_app
    from wechat_agent.workspace import agent

    monkeypatch.setattr(
        Runtime, "collect", lambda self: self.db.heartbeat("collector", "synthetic")
    )
    monkeypatch.setattr(agent, "create_client", lambda: model(ready))
    headers = {"Authorization": "Bearer " + ready.token}
    with TestClient(create_app(ready.settings, background=True)) as c:
        assert (
            c.post(
                "/api/workspace/automation", headers=headers, json={"enabled": True}
            ).status_code
            == 200
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            documents = c.get("/api/workspace/documents", headers=headers).json()
            if documents["items"]:
                break
            time.sleep(0.02)
        assert documents["items"][0]["name"] == "张先生"
        assert documents["items"][0]["today_action_ids"]
        assert c.get("/api/workspace/queue", headers=headers).json()["background"]
