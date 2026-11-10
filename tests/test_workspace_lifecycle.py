"""Full customer workflow using synthetic archives and a mock model only."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from test_media import setup as image_setup
from test_workspace import pilot as _pilot
from test_workspace import proposal

from wechat_agent.ingestion import ingest
from wechat_agent.web import create_app
from wechat_agent.workspace import ocr, queue
from wechat_agent.workspace.context import build, snapshot
from wechat_agent.workspace.drafts import generate
from wechat_agent.workspace.presentation import history, journal
from wechat_agent.workspace.schema import Decision
from wechat_agent.workspace.store import command, commit, raw, reference, valid_refs
from wechat_agent.workspace.views import details, sources

pilot = _pilot


def publish(db):
    ctx, result = proposal(db)
    return commit(db, "merchant", result, ctx, snapshot(db, "merchant"))


def test_followup_is_durable_feedback_and_requeues_unchanged_chat(pilot):
    db = pilot
    doc = publish(db)
    aid = next(iter(doc["body"]["actions"]))
    queue.configure(db, True)
    assert queue.report(db)["counts"] == {"succeeded": 1}
    updated = command(
        db,
        "merchant",
        doc["version"],
        "followup",
        value={
            "outcome": "contacted",
            "note": "已在微信确认等待报价反馈",
            "action_id": aid,
            "action_state": "waiting",
            "next_date": (
                datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=2)
            ).isoformat(),
        },
    )
    assert updated["body"]["actions"][aid]["state"] == "waiting"
    assert journal(db, "merchant")["items"][0]["outcome"] == "contacted"
    queue.reconcile(db)
    assert queue.report(db)["counts"] == {"queued": 1}
    again = publish(db)
    assert again["body"]["actions"][aid]["state"] == "waiting"
    assert any(h["operation"] == "followup" for h in again["body"]["history"])
    assert history(db, "merchant")[0]["version"] == again["version"]
    assert len(db.rows("SELECT * FROM usage")) == 0
    assert not db.rows("SELECT * FROM events WHERE kind='message_sent'")


def test_followup_rejects_unlinked_dates_and_does_not_change_batch(pilot):
    doc = publish(pilot)
    with pytest.raises(ValueError, match="workspace_action_required"):
        command(
            pilot,
            "merchant",
            doc["version"],
            "followup",
            value={"outcome": "contacted", "note": "已联系", "action_state": "done"},
        )
    assert journal(pilot, "merchant")["items"] == []
    changed = command(
        pilot,
        "merchant",
        doc["version"],
        "followup",
        value={"outcome": "replied", "note": "客户已回复"},
    )
    assert next(iter(changed["body"]["batches"].values()))["stage"] == "needs"


def test_manual_batch_stage_survives_model_and_stops_actions(pilot):
    doc = publish(pilot)
    bid = next(iter(doc["body"]["batches"]))
    changed = command(
        pilot,
        "merchant",
        doc["version"],
        "batch_stage",
        bid,
        {"stage": "fulfillment", "note": "已核对实际发车轨迹"},
    )
    assert all(a["state"] == "cancelled" for a in changed["body"]["actions"].values())
    again = publish(pilot)
    assert again["body"]["batches"][bid]["stage"] == "fulfillment"
    assert again["body"]["batches"][bid]["stage_locked"]
    assert not details(pilot, "merchant")["today_action_ids"]
    unlocked = command(
        pilot, "merchant", again["version"], "batch_stage", bid, {"stage": "auto"}
    )
    assert not unlocked["body"]["batches"][bid]["stage_locked"]


def test_decision_is_scoped_to_batch_not_only_type(pilot, record):
    ctx, p = proposal(pilot)
    first = p.batches[0].origin
    p.decisions = [
        Decision(
            key="batch",
            blocks_followup=True,
            impact="确定当前需求归属",
            batch=first,
            text="确认英国批次需求",
            evidence=[first],
        )
    ]
    doc = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    did = next(iter(doc["body"]["decisions"]))
    command(pilot, "merchant", doc["version"], "decision", did, "英国批次已确认")
    ingest(
        pilot,
        [
            record
            | {
                "source_id": "second",
                "sender_id": "merchant",
                "text": "另一批德国货",
                "event_time": "2026-11-09T12:00:00+08:00",
            }
        ],
    )
    ctx, p = proposal(pilot)
    second = next(k for k, v in ctx["evidence"].items() if v["text"] == "另一批德国货")
    p.batches[0].origin = second
    p.batches[0].evidence = [second]
    p.actions = []
    p.decisions = [
        Decision(
            key="batch",
            blocks_followup=True,
            impact="确定当前需求归属",
            batch=second,
            text="确认德国批次需求",
            evidence=[second],
        )
    ]
    doc = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert doc["body"]["decisions"][did]["resolved"]
    assert len([d for d in doc["body"]["decisions"].values() if not d["resolved"]]) == 1


def test_draft_uses_verified_action_and_is_cached_without_sending(pilot):
    doc = publish(pilot)
    aid = next(iter(doc["body"]["actions"]))
    requests = []

    def respond(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        requests.append(payload)
        assert payload["action"]["text"] == "确认报价"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "text": "您好，想确认下这批货的报价进展，方便时请回复。",
                                    "evidence": [payload["messages"][0]["ref"]],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 37},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        draft = generate(pilot, "merchant", aid, doc["version"], client)
        assert not draft["cached"] and len(draft["evidence"]) == 1
        assert generate(pilot, "merchant", aid, doc["version"], client)["cached"]
    assert len(requests) == 1
    assert pilot.rows("SELECT actual FROM usage") == [{"actual": 37}]
    assert raw(pilot, "merchant")["version"] == doc["version"]
    assert journal(pilot, "merchant")["items"] == []
    paused = command(pilot, "merchant", doc["version"], "pause", value=True)
    with pytest.raises(ValueError, match="workspace_draft_not_ready"):
        generate(pilot, "merchant", aid, paused["version"])


def test_ocr_candidate_is_not_input_until_human_confirmation(
    db, chat, record, monkeypatch
):
    client, h, mid, _ = image_setup(db, chat, record | {"sender_id": "merchant"})
    from wechat_agent.crm import configure

    configure(db, True)
    from wechat_agent.workspace.views import source_people

    assert not source_people(db)[0]["has_text"]
    before = snapshot(db, "merchant", False)
    monkeypatch.setattr(
        ocr, "recognize_bytes", lambda _: ("运单TEST20261109 已发车", "test-local")
    )
    result = client.post(f"/api/workspace/images/{mid}/recognize", headers=h, json={})
    assert result.status_code == 200, result.text
    assert snapshot(db, "merchant", False) == before
    assert "TEST20261109" not in str(build(db, "merchant")["payload"])
    state = result.json()
    verified = client.post(
        f"/api/workspace/images/{mid}/text",
        headers=h,
        json={"version": state["version"], "text": state["candidate_text"]},
    )
    assert verified.status_code == 200, verified.text
    assert snapshot(db, "merchant", False) != before
    assert source_people(db)[0]["has_text"]
    ctx = build(db, "merchant")
    msg = next(v for v in ctx["evidence"].values() if v["id"] == mid)
    assert "TEST20261109" in msg["text"] and msg["extraction_version"] == 1
    assert (
        db.rows("SELECT text FROM messages WHERE id=?", (mid,))[0]["text"] == "[图片]"
    )
    refs = [reference(msg)]
    assert valid_refs(db, refs)
    assert (
        client.post(
            f"/api/workspace/images/{mid}/text",
            headers=h,
            json={"version": 0, "text": "错版本"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/workspace/images/{mid}/text",
            headers=h,
            json={"version": 1, "text": "核对后的文字"},
        ).status_code
        == 200
    )
    assert not valid_refs(db, refs)
    db.settings.source_account = "other"
    assert client.get(f"/api/workspace/images/{mid}", headers=h).status_code == 422


def test_unified_settings_and_compact_customer_api(pilot):
    doc = publish(pilot)
    c = TestClient(create_app(pilot.settings))
    h = {"Authorization": "Bearer " + pilot.token}
    data = c.get("/api/workspace/settings", headers=h).json()
    assert data["account_id"] == "account" and len(data["week"]) == 7
    assert "test-only" not in json.dumps(data)
    assert c.get("/health", headers=h).json()["schema"] == 16
    assert (
        c.get("/api/workspace/documents", headers=h).json()["items"][0]["evidence"]
        == []
    )
    assert (
        c.get("/api/workspace/customer?source_id=merchant", headers=h).json()["id"]
        == doc["id"]
    )
    assert (
        len(
            c.get("/api/workspace/customer?source_id=merchant", headers=h).json()[
                "evidence"
            ]
        )
        == 1
    )
    for path in ["/", "/workspace", "/?page=settings", "/?page=scope"]:
        assert 'type="module"' in c.get(path, headers=h).text
    assert "page-settings" in c.get("/legacy", headers=h).text
    people = c.get("/api/crm/people?q=张先生", headers=h).json()
    assert people["items"][0]["name"] == "张先生"


def test_timeline_search_and_order_only_affect_presentation(pilot, record):
    ingest(
        pilot,
        [
            record
            | {
                "source_id": "later",
                "sender_id": "merchant",
                "text": "另一条海运问询",
                "event_time": "2026-11-09T12:00:00+08:00",
            }
        ],
    )
    before = snapshot(pilot, "merchant", False)
    assert sources(pilot, "merchant")["items"][0]["text"] == "下周英国3方货，请确认报价"
    assert (
        sources(pilot, "merchant", order="latest")["items"][0]["text"]
        == "另一条海运问询"
    )
    assert sources(pilot, "merchant", q="海运")["total"] == 1
    assert (
        snapshot(pilot, "merchant", False) == before
        and len(build(pilot, "merchant")["evidence"]) == 2
    )


def test_v13_backup_preserves_queue_documents_and_messages(pilot):
    import sqlite3

    from wechat_agent.db import DB

    doc = publish(pilot)
    queue.configure(pilot, True)
    with pilot.tx() as c:
        c.execute("DROP TABLE message_extractions")
        c.execute("PRAGMA user_version=12")
    DB(pilot.settings)
    backup = sorted(pilot.settings.data_dir.glob("pre-v13-*.sqlite3"))[-1]
    with sqlite3.connect(backup) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 12
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert (
            c.execute("SELECT version FROM workspace_documents").fetchone()[0]
            == doc["version"]
        )
    assert queue.settings(pilot)["enabled"]
    assert not pilot.rows("SELECT * FROM message_extractions")


def test_draft_rejects_invented_quantity_and_retains_paid_usage(pilot):
    doc = publish(pilot)
    aid = next(iter(doc["body"]["actions"]))

    def respond(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "text": "您好，报价是999元每方。",
                                    "evidence": [payload["messages"][0]["ref"]],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(ValueError, match="workspace_draft_schema"):
            generate(pilot, "merchant", aid, doc["version"], client)
    assert len(pilot.rows("SELECT * FROM usage")) == 2
    assert not pilot.rows("SELECT * FROM events WHERE kind='workspace_draft'")


def test_manual_batch_constraint_survives_source_revision(pilot):
    doc = publish(pilot)
    bid = next(iter(doc["body"]["batches"]))
    command(
        pilot,
        "merchant",
        doc["version"],
        "batch_stage",
        bid,
        {"stage": "fulfillment", "note": "人工核对已实际发车"},
    )
    with pilot.tx() as c:
        c.execute("UPDATE messages SET revision=revision+1")
    ctx = build(pilot, "merchant")
    assert ctx["payload"]["document"]["batch_overrides"][bid]["stage"] == "fulfillment"
    again = publish(pilot)
    assert again["body"]["batches"][bid]["stage_locked"]
    assert again["body"]["batches"][bid]["stage"] == "fulfillment"


def test_parallel_draft_requests_do_not_double_bill(pilot):
    import fcntl
    import os

    from wechat_agent.analysis import Blocked
    from wechat_agent.workspace.store import stable

    doc = publish(pilot)
    aid = next(iter(doc["body"]["actions"]))
    path = pilot.settings.data_dir / (
        "workspace-draft-" + stable(pilot.settings.source_account, "merchant") + ".lock"
    )
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(Blocked, match="workspace_draft_running"):
            generate(pilot, "merchant", aid, doc["version"])
        assert not pilot.rows("SELECT * FROM usage")
    finally:
        os.close(fd)


def test_image_explicit_refresh_bypasses_thumbnail_cache(db, chat, record):
    client, h, mid, requests = image_setup(db, chat, record)
    assert client.get(f"/api/workspace/images/{mid}", headers=h).status_code == 200
    n = len(requests)
    assert client.get(f"/api/workspace/images/{mid}", headers=h).status_code == 200
    assert len(requests) == n
    assert (
        client.get(f"/api/workspace/images/{mid}?refresh=true", headers=h).status_code
        == 200
    )
    assert len(requests) > n
