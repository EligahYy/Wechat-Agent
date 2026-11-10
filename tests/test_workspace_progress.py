"""Customer job controls, active pagination, and bounded fact packet recovery."""

import json

import pytest
from test_workspace_queue import model
from test_workspace_queue import ready as ready

from wechat_agent.analysis import Blocked
from wechat_agent.db import DB, dumps, now
from wechat_agent.ingestion import ingest
from wechat_agent.workspace import agent, queue
from wechat_agent.workspace.context import build, snapshot
from wechat_agent.workspace.packets import prepare
from wechat_agent.workspace.schema import FactBook
from wechat_agent.workspace.store import read
from wechat_agent.workspace.transport import FactbookError, ModelSession


@pytest.mark.parametrize("phase", ["extract", "review"])
def test_customer_pause_stops_publication_and_resume_reuses_packets(ready, phase):
    db = ready
    stopped = []

    def pause(payload):
        if not stopped and (
            payload.get("phase") == phase or phase == "review" and "draft" in payload
        ):
            stopped.append(True)
            queue._transition(db, "merchant", "pause")

    queue.configure(db, True)
    with model(db, pause) as client:
        assert queue.step(db, client=client)
    assert not read(db, "merchant")
    assert queue.progress(db)["items"][0]["user_paused"]
    calls = len(db.rows("SELECT * FROM usage"))
    saved = len(db.rows("SELECT * FROM workspace_packets"))
    assert saved == 1
    # The durable stop survives restart, global toggles and indexing.
    DB(db.settings)
    queue.configure(db, False)
    queue.configure(db, True)
    with model(db) as client:
        assert not queue.step(db, client=client)
        assert len(db.rows("SELECT * FROM usage")) == calls
        with pytest.raises(Blocked, match="workspace_customer_paused"):
            agent.run(db, "merchant", client)
        queue._transition(db, "merchant", "resume")
        assert queue.step(db, client=client)
    assert read(db, "merchant")
    assert queue.progress(db)["items"] == []
    assert len(db.rows("SELECT * FROM workspace_packets")) == saved


def test_fast_pause_resume_does_not_publish_previous_generation(ready):
    db = ready
    changed = []

    def toggle(payload):
        if "draft" in payload and not changed:
            changed.append(True)
            queue._transition(db, "merchant", "pause")
            queue._transition(db, "merchant", "resume")

    queue.configure(db, True)
    with model(db, toggle) as client:
        assert queue.step(db, client=client)
    assert not read(db, "merchant")
    assert db.rows("SELECT status,control_version FROM workspace_queue")[0] == {
        "status": "queued",
        "control_version": 2,
    }
    with model(db) as client:
        assert queue.step(db, client=client)
    assert read(db, "merchant")


def test_new_messages_do_not_unpause_customer(ready, record):
    queue._transition(ready, "merchant", "pause")
    ingest(
        ready,
        [
            record
            | {"source_id": "later", "sender_id": "merchant", "text": "新消息仍需保留"}
        ],
    )
    queue.reconcile(ready)
    row = ready.rows("SELECT * FROM workspace_queue")[0]
    assert row["user_paused"] == 1 and row["status"] == "paused"


def test_progress_pagination_is_customer_scoped_newest_and_hides_complete(
    ready, record
):
    ingest(
        ready,
        [
            record | {"source_id": f"row-{n}", "sender_id": f"person-{n}"}
            for n in range(45)
        ],
    )
    queue.reconcile(ready)
    with ready.tx() as c:
        for n in range(45):
            c.execute(
                "UPDATE workspace_queue SET updated_at=? WHERE source_id=?",
                (f"2026-11-09T10:00:{n:02d}+00:00", f"person-{n}"),
            )
        c.execute(
            "UPDATE workspace_queue SET status='succeeded' WHERE source_id='merchant'"
        )
        c.execute(
            "UPDATE workspace_queue SET status='succeeded' WHERE source_id='person-44'"
        )
        c.execute(
            "INSERT INTO actor_exclusions VALUES('account','person-43',?)",
            (now(),),
        )
        c.execute(
            "INSERT INTO workspace_queue(account_id,source_id,input_revision,status,priority,available_at,updated_at) VALUES('other','foreign','x','running',0,?,?)",
            (now(), now()),
        )
    first = queue.progress(ready)
    second = queue.progress(ready, 2)
    last = queue.progress(ready, 999)
    assert (first["total"], first["page_size"], first["pages"]) == (43, 20, 3)
    assert len(first["items"]) == len(second["items"]) == 20
    assert first["items"][0]["source_id"] == "person-42"
    assert not set(i["source_id"] for i in first["items"]) & set(
        i["source_id"] for i in second["items"]
    )
    assert last["page"] == 3 and len(last["items"]) == 3 and not last["has_more"]
    assert not ready.rows("SELECT * FROM usage")
    with pytest.raises(ValueError, match="workspace_invalid_query"):
        queue.progress(ready, 0)


def test_v14_upgrade_keeps_archives_and_wakes_old_budget_jobs(ready):
    import sqlite3

    queue.reconcile(ready)
    with ready.tx() as c:
        c.execute("ALTER TABLE workspace_queue DROP COLUMN user_paused")
        c.execute("ALTER TABLE workspace_queue DROP COLUMN control_version")
        c.execute(
            "UPDATE workspace_queue SET status='paused',error='blocked_budget',available_at='2099-01-01'"
        )
        c.execute("PRAGMA user_version=13")
    DB(ready.settings)
    backup = sorted(ready.settings.data_dir.glob("pre-v14-*.sqlite3"))[-1]
    with sqlite3.connect(backup) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 13
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert ready.rows("SELECT status,user_paused,control_version FROM workspace_queue")[
        0
    ] == {"status": "queued", "user_paused": 0, "control_version": 0}


def response(book, reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"content": dumps(book)}}]}


def test_factbook_repairs_with_safe_fields_and_splits_truncation_immediately():
    class Session:
        factbook = ModelSession.factbook
        payloads = []

        def request(self, prompt, payload):
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                return response({"facts": [{"text": "private contents"}]})
            return response({"facts": []})

    session = Session()
    session.factbook("prompt", {"phase": "merge"})
    repair = session.payloads[1]
    assert "facts.0.evidence:missing" in repair["validation_issues"]
    assert "private contents" not in dumps(repair)
    session.request = lambda *_: response({}, "length")
    with pytest.raises(FactbookError, match="workspace_fact_truncated"):
        session.factbook("prompt", {})


def test_adaptive_merge_preserves_all_sources_and_reuses_extracted_packets(
    ready, record
):
    ingest(
        ready,
        [
            record
            | {
                "source_id": f"history-{n}",
                "sender_id": "merchant",
                "text": f"第{n}条完整资料" + "原始业务信息" * 65,
            }
            for n in range(70)
        ],
    )
    context = build(ready, "merchant")
    calls = []

    class Session:
        fingerprint = snapshot(ready, "merchant")
        factbook = ModelSession.factbook

        def ensure_active(self):
            pass

        def request(self, prompt, payload):
            calls.append(payload)
            if payload["phase"] == "extract":
                facts = [
                    {
                        "text": m["text"][:450],
                        "kind": "context",
                        "subject": "customer",
                        "evidence": [m["ref"]],
                    }
                    for m in payload["messages"]
                ]
            elif len(payload["facts"]) > 2:
                return response({}, "length")
            else:
                facts = [
                    {
                        "text": "合并资料，完整来源仍保留",
                        "kind": "context",
                        "subject": "customer",
                        "evidence": list(
                            dict.fromkeys(
                                r for f in payload["facts"] for r in f["evidence"]
                            )
                        ),
                    }
                ]
            return response({"facts": facts})

    result = prepare(ready, "merchant", context, Session())
    assert any(p["phase"] == "merge" and len(p["facts"]) > 2 for p in calls)
    assert {r for f in result["facts"] for r in f["evidence"]} == set(
        context["evidence"]
    )
    assert (
        ready.rows("SELECT processed_messages FROM workspace_scans")[0][
            "processed_messages"
        ]
        == 71
    )
    extracted = len([p for p in calls if p["phase"] == "extract"])
    assert extracted > 1
    calls.clear()
    result2 = prepare(ready, "merchant", build(ready, "merchant"), Session())
    assert result2 == result and not calls
    assert len(ready.rows("SELECT * FROM messages")) == 71
    assert all(
        FactBook.model_validate(json.loads(p["body"]))
        for p in ready.rows("SELECT body FROM workspace_packets WHERE kind='extract'")
    )


def test_progress_api_auth_validation_and_customer_isolation(ready):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    client = TestClient(create_app(ready.settings))
    assert client.get("/api/workspace/progress").status_code == 401
    headers = {"Authorization": "Bearer " + ready.token}
    queue.reconcile(ready)
    assert (
        client.get("/api/workspace/progress", headers=headers).json()["page_size"] == 20
    )
    assert (
        client.get("/api/workspace/progress?page=0", headers=headers).status_code == 422
    )
    for data in (
        {"source_id": "merchant", "action": "delete"},
        {"source_id": "foreign", "action": "pause"},
        {"action": "pause"},
    ):
        assert (
            client.post(
                "/api/workspace/progress/control", headers=headers, json=data
            ).status_code
            == 422
        )
    assert not client.post(
        "/api/workspace/progress/control",
        headers=headers,
        json={"source_id": "merchant", "action": "pause"},
    ).json()["paused"]
    assert not client.get("/api/workspace/progress", headers=headers).json()["items"][
        0
    ]["user_paused"]
    assert not ready.rows("SELECT * FROM usage")


def test_invalid_evidence_is_never_accepted_by_packet_splitting(ready):
    class Session:
        fingerprint = snapshot(ready, "merchant")
        calls = 0

        def ensure_active(self):
            pass

        def factbook(self, *_):
            self.calls += 1
            return FactBook.model_validate(
                {
                    "facts": [
                        {
                            "text": "fabricated",
                            "subject": "customer",
                            "kind": "context",
                            "evidence": ["invented-ref"],
                        }
                    ]
                }
            )

    session = Session()
    with pytest.raises(ValueError, match="workspace_unknown_evidence"):
        prepare(ready, "merchant", build(ready, "merchant"), session)
    assert session.calls == 1
    assert not ready.rows("SELECT * FROM workspace_packets")


def test_cached_manual_resume_finishes_job_without_new_model_calls(ready):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    with model(ready) as client:
        agent.run(ready, "merchant", client)
    calls = len(ready.rows("SELECT * FROM usage"))
    queue._transition(ready, "merchant", "pause")
    queue._transition(ready, "merchant", "resume")
    client = TestClient(create_app(ready.settings))
    result = client.post(
        "/api/workspace/analyze",
        headers={"Authorization": "Bearer " + ready.token},
        json={"source_id": "merchant"},
    )
    assert result.json()["cached"]
    assert queue.progress(ready)["items"] == []
    assert queue.report(ready)["counts"] == {"succeeded": 1}
    assert len(ready.rows("SELECT * FROM usage")) == calls
