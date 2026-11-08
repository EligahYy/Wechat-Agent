import json

import httpx
import pytest

from wechat_agent.crm import configure
from wechat_agent.db import dumps
from wechat_agent.ingestion import ingest
from wechat_agent.services import Conflict, allow_conversation
from wechat_agent.workspace.agent import run
from wechat_agent.workspace.context import build, snapshot
from wechat_agent.workspace.schema import Proposal
from wechat_agent.workspace.store import command, commit, read
from wechat_agent.workspace.views import listing


@pytest.fixture
def pilot(db, chat, record, monkeypatch):
    db.settings.bind_source("account")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    configure(db, True)
    ingest(
        db, [record | {"sender_id": "merchant", "text": "下周英国3方货，请确认报价"}]
    )
    with db.tx() as c:
        c.execute(
            "INSERT INTO identity_metadata VALUES('account','merchant','张先生','张','', '2026-11-08')"
        )
    return db


def proposal(db):
    ctx = build(db, "merchant")
    key = next(k for k, v in ctx["evidence"].items() if v["anchor"])
    p = Proposal.model_validate(
        {
            "relationship": "merchant",
            "evidence": [key],
            "notes": [{"text": "关注英国", "evidence": [key]}],
            "batches": [
                {
                    "origin": key,
                    "text": "英国第一批",
                    "stage": "needs",
                    "evidence": [key],
                }
            ],
            "actions": [
                {
                    "origin": key,
                    "batch": key,
                    "kind": "confirm_quote",
                    "text": "确认报价",
                    "reason": "商家有具体备货意向",
                    "state": "open",
                    "owner": "platform",
                    "evidence": [key],
                }
            ],
        }
    )
    return ctx, p


def test_document_versions_manual_lock_and_cross_conversation(pilot, record):
    db = pilot
    allow_conversation(
        db,
        "fixture",
        "account",
        "merchant",
        "商家私信",
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
                "conversation_id": "merchant",
                "conversation_type": "private",
                "source_id": "private1",
                "sender_id": "merchant",
                "text": "同一批英国货",
            }
        ],
    )
    ctx, p = proposal(db)
    assert len(ctx["evidence"]) == 2
    d = commit(db, "merchant", p, ctx, snapshot(db, "merchant"))
    aid = next(iter(d["body"]["actions"]))
    command(db, "merchant", d["version"], "action", aid, "done")
    with pytest.raises(Conflict):
        command(db, "merchant", d["version"], "pause", value=True)
    d = commit(db, "merchant", p, ctx, snapshot(db, "merchant"))
    assert d["body"]["actions"][aid]["state"] == "done"
    assert len(db.rows("SELECT * FROM workspace_documents")) == 1
    assert len(db.rows("SELECT * FROM workspace_versions")) == 3


def test_exclusion_and_source_change_during_request(pilot):
    ctx, p = proposal(pilot)
    fp = snapshot(pilot, "merchant")
    with pilot.tx() as c:
        c.execute("INSERT INTO actor_exclusions VALUES('account','merchant','同事')")
    with pytest.raises(ValueError, match="excluded"):
        commit(pilot, "merchant", p, ctx, fp)
    assert listing(pilot)["items"] == []


def test_stale_revision_and_unknown_evidence_never_write(pilot):
    ctx, p = proposal(pilot)
    fp = snapshot(pilot, "merchant")
    with pilot.tx() as c:
        c.execute("UPDATE messages SET revision=revision+1")
    with pytest.raises(Conflict):
        commit(pilot, "merchant", p, ctx, fp)
    ctx, p = proposal(pilot)
    p.evidence = ["invented"]
    with pytest.raises(ValueError, match="unknown_evidence"):
        commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert not pilot.rows("SELECT * FROM workspace_documents")


def test_shipment_closes_batch_and_old_request_cannot_reopen(pilot):
    ctx, p = proposal(pilot)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    p.batches[0].ref = next(iter(d["body"]["batches"]))
    p.batches[0].stage = "reported_shipped"
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert all(a["state"] == "cancelled" for a in d["body"]["actions"].values())
    p.batches[0].stage = "needs"
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert all(b["stage"] == "reported_shipped" for b in d["body"]["batches"].values())


def test_agent_tool_loop_budget_and_completed_input_reuse(pilot):
    calls = []

    def respond(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(payload)
        if len(calls) == 1:
            body = {"search": "英国"}
        else:
            ctx, p = proposal(pilot)
            body = {"proposal": p.model_dump()}
            if "draft" in payload:
                body["checked"] = True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": dumps(body)}}
                ],
                "usage": {"total_tokens": 100},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        run(pilot, "merchant", client)
        assert run(pilot, "merchant", client)["cached"]
    assert len(calls) == 3
    assert sum(r["actual"] for r in pilot.rows("SELECT * FROM usage")) == 300
    assert "手机号" not in dumps(calls)
    assert read(pilot, "merchant")["version"] == 1


def test_malformed_model_output_is_bounded_and_audited(pilot):
    def respond(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {"total_tokens": 10},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(ValueError, match="empty_proposal"):
            run(pilot, "merchant", client)
    assert pilot.rows("SELECT status FROM workspace_runs")[0]["status"] == "failed"
    assert not pilot.rows("SELECT * FROM workspace_documents")


def test_partial_context_does_not_manufacture_action(pilot):
    ctx, p = proposal(pilot)
    ctx["complete"] = False
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert d["body"]["batches"]
    assert all(a["state"] == "proposed" for a in d["body"]["actions"].values())


def test_manual_role_is_structured_and_survives_reanalysis(pilot):
    from wechat_agent.workspace.schema import Decision

    ctx, p = proposal(pilot)
    p.decisions = [Decision(key="role", text="角色待确认", evidence=p.evidence)]
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    command(pilot, "merchant", d["version"], "decision", "role", "non_target")
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert d["body"]["relationship"] == "non_target"
    assert listing(pilot)["items"] == []


def test_api_auth_scope_and_version(pilot):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    ctx, p = proposal(pilot)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    c = TestClient(create_app(pilot.settings))
    assert c.get("/workspace").status_code == 401
    h = {"Authorization": "Bearer " + pilot.token}
    assert c.get("/workspace", headers=h).status_code == 200
    assert (
        c.get("/api/workspace/documents", headers=h).json()["items"][0]["name"]
        == "张先生"
    )
    r = c.post(
        "/api/workspace/command",
        headers=h,
        json={
            "source_id": "merchant",
            "version": d["version"],
            "operation": "pause",
            "value": True,
        },
    )
    assert r.status_code == 200
    assert (
        c.post(
            "/api/workspace/command",
            headers=h,
            json={
                "source_id": "merchant",
                "version": d["version"],
                "operation": "pause",
                "value": False,
            },
        ).status_code
        == 409
    )
    with pilot.tx() as conn:
        conn.execute("INSERT INTO actor_exclusions VALUES('account','merchant','test')")
    assert c.get("/api/workspace/documents", headers=h).json()["items"] == []
    assert c.get("/api/workspace/candidates", headers=h).json()["items"] == []


def test_old_followup_is_withheld_when_new_source_is_unread(pilot, record):
    from wechat_agent.workspace.views import details

    ctx, p = proposal(pilot)
    commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert details(pilot, "merchant")["can_followup"]
    ingest(
        pilot,
        [
            record
            | {"source_id": "later", "sender_id": "merchant", "text": "我不发这批了"}
        ],
    )
    assert not details(pilot, "merchant")["can_followup"]
    assert details(pilot, "merchant")["needs_update"]


def test_later_reply_outside_three_messages_is_in_context(pilot, record):
    ingest(
        pilot,
        [
            record
            | {
                "source_id": f"other{i}",
                "sender_id": "provider",
                "text": f"背景 {i}",
                "event_time": f"2026-11-04T09:{i + 1:02d}:00+08:00",
            }
            for i in range(8)
        ],
    )
    ingest(
        pilot,
        [
            record
            | {
                "source_id": "answer",
                "sender_id": "provider",
                "text": "报价已经确认了",
                "event_time": "2026-11-04T09:15:00+08:00",
            }
        ],
    )
    ctx = build(pilot, "merchant")
    assert any(m["text"] == "报价已经确认了" for m in ctx["evidence"].values())


def test_failed_response_replay_has_no_new_billing(pilot):
    calls = []

    def respond(request):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "invalid-json"}}
                ],
                "usage": {"total_tokens": 5},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        for _ in range(2):
            with pytest.raises(ValueError, match="workspace_model_schema"):
                run(pilot, "merchant", client)
    assert len(calls) == 3
    assert sum(r["actual"] for r in pilot.rows("SELECT * FROM usage")) == 15


def test_no_reentrant_model_spending(pilot):
    from wechat_agent.analysis import Blocked

    def respond(request):
        with pytest.raises(Blocked, match="workspace_already_running"):
            run(pilot, "merchant")
        _, p = proposal(pilot)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": dumps(
                                {
                                    "proposal": p.model_dump(),
                                    **(
                                        {"checked": True}
                                        if "draft"
                                        in json.loads(
                                            json.loads(request.content)["messages"][1][
                                                "content"
                                            ]
                                        )
                                        else {}
                                    ),
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        run(pilot, "merchant", client)
    assert len(pilot.rows("SELECT * FROM usage")) == 2


def test_pilot_runtime_does_not_schedule_legacy_model(pilot, monkeypatch):
    from wechat_agent import runtime
    from wechat_agent.runtime import Runtime

    worker = Runtime(pilot)
    pilot.settings.analysis_mode = "pilot"

    def forbidden(*args):
        raise AssertionError("legacy model must not run")

    monkeypatch.setattr(runtime, "schedule", forbidden)
    monkeypatch.setattr(runtime, "run_once", forbidden)
    monkeypatch.setattr(worker.stop, "wait", lambda timeout: worker.stop.set())
    worker.analyze()
    assert (
        pilot.rows("SELECT status FROM runtime WHERE name='worker'")[0]["status"]
        == "pilot_manual"
    )


def test_v10_backup_keeps_archive_and_budget(pilot):
    import sqlite3

    from wechat_agent.db import DB

    with pilot.tx() as c:
        c.execute("PRAGMA user_version=9")
    count = len(pilot.rows("SELECT * FROM messages"))
    migrated = DB(pilot.settings)
    backups = list(pilot.settings.data_dir.glob("pre-v10-*.sqlite3"))
    assert backups
    with sqlite3.connect(backups[-1]) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 9
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == count
    assert migrated.rows("PRAGMA user_version")[0]["user_version"] == 10
    assert len(migrated.rows("SELECT * FROM messages")) == count


def test_legacy_pause_is_preserved_until_explicit_new_override(pilot):
    from wechat_agent.workspace.views import details

    with pilot.tx() as c:
        c.execute(
            "INSERT INTO crm_customers(id,contact_id,account_id,name,do_not_contact,created_at) SELECT 'old-customer',id,'account','旧客户',1,'2026-11-01' FROM crm_contacts WHERE account_id='account' AND source_id='merchant'"
        )
    ctx, p = proposal(pilot)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert d["body"]["paused"]
    assert not details(pilot, "merchant")["can_followup"]
    command(pilot, "merchant", d["version"], "pause", value=False)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert not d["body"]["paused"]


def test_candidates_visible_without_model_authorization(pilot):
    from wechat_agent.analysis import Blocked
    from wechat_agent.workspace.views import candidates

    configure(pilot, False)
    data = candidates(pilot)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "张先生"
    assert data["items"][0]["blocked_reason"] == "analysis_disabled"
    assert data["diagnostics"]["archived_messages"] == 1
    assert not data["diagnostics"]["empty_reason"]
    assert build(pilot, "merchant")["evidence"] == {}
    with pytest.raises(Blocked, match="blocked_policy"):
        run(pilot, "merchant")
    assert pilot.rows("SELECT * FROM workspace_runs") == []


def test_candidates_private_outgoing_and_unknown_group_direction(pilot, record):
    from wechat_agent.workspace.views import candidates

    allow_conversation(
        pilot,
        "fixture",
        "account",
        "peer",
        "私信备注",
        "private",
        None,
        None,
        True,
        followup_source=True,
    )
    ingest(
        pilot,
        [
            record
            | {
                "conversation_id": "peer",
                "conversation_type": "private",
                "source_id": "p1",
                "sender_id": "account",
                "direction": "outgoing",
            },
            record | {"source_id": "g2", "sender_id": "known", "direction": "unknown"},
            record
            | {"source_id": "g3", "sender_id": "unknown", "direction": "unknown"},
            record
            | {"source_id": "g4", "sender_id": "account", "direction": "unknown"},
            record
            | {"source_id": "g5", "sender_id": "123@chatroom", "direction": "unknown"},
        ],
    )
    data = candidates(pilot)
    assert {r["source_id"] for r in data["items"]} == {"peer", "known", "merchant"}
    peer = candidates(pilot, q="私信备注")["items"][0]
    assert peer["source_id"] == "peer"
    assert peer["blocked_reason"] is None
    assert candidates(pilot, page=99)["page"] == 1
    assert candidates(pilot, q="does-not-exist")["total"] == 0
    assert candidates(pilot, q="does-not-exist")["diagnostics"]["contacts"] == 3


def test_candidates_exclusions_account_scope_and_readiness(pilot, record, monkeypatch):
    from wechat_agent.workspace.views import candidates

    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert candidates(pilot)["items"][0]["blocked_reason"] == "key_missing"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    with pilot.tx() as c:
        c.execute("UPDATE conversations SET egress=0")
    assert candidates(pilot)["items"][0]["blocked_reason"] == "source_unauthorized"
    with pilot.tx() as c:
        c.execute("UPDATE conversations SET egress=1")
        c.execute("UPDATE messages SET type='image'")
    assert candidates(pilot)["items"][0]["blocked_reason"] == "no_text"
    with pilot.tx() as c:
        c.execute("INSERT INTO actor_exclusions VALUES('account','merchant','同事')")
    assert candidates(pilot)["items"] == []
    with pilot.tx() as c:
        c.execute("DELETE FROM actor_exclusions")
        c.execute("UPDATE conversations SET followup_source=0")
    assert candidates(pilot)["diagnostics"]["empty_reason"] == "scope_excluded"
    assert candidates(pilot)["items"] == []
    pilot.settings.bind_source("other-account")
    assert candidates(pilot)["diagnostics"]["empty_reason"] == "no_archive"
    assert candidates(pilot)["items"] == []


def test_candidates_empty_diagnostics(db, chat, record):
    from wechat_agent.workspace.views import candidates

    assert candidates(db)["diagnostics"]["empty_reason"] == "account_unbound"
    db.settings.bind_source("account")
    assert candidates(db)["diagnostics"]["empty_reason"] == "no_archive"
    ingest(db, [record | {"sender_id": "unknown", "direction": "unknown"}])
    assert candidates(db)["diagnostics"]["empty_reason"] == "no_identity"


def test_transport_grounding_and_pending_task_confirmation(pilot):
    from wechat_agent.workspace.views import details

    ctx, p = proposal(pilot)
    p.notes[0].text = "询问汽运"
    with pytest.raises(ValueError, match="transport_term"):
        commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    p.notes[0].text = "询问海运"
    with pytest.raises(ValueError, match="transport_evidence"):
        commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    p.notes[0].text = "CUSTOMER关注英国"
    ctx["complete"] = False
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    aid = next(iter(d["body"]["actions"]))
    assert not details(pilot, "merchant")["today_action_ids"]
    d = command(pilot, "merchant", d["version"], "confirm_action", aid, True)
    assert details(pilot, "merchant")["today_action_ids"] == [aid]
    d = command(pilot, "merchant", d["version"], "action", aid, "done")
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert d["body"]["actions"][aid]["state"] == "done"
    assert "CUSTOMER" not in dumps(d["body"]["notes"])


def test_corrected_note_survives_review(pilot):
    ctx, p = proposal(pilot)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    nid = next(iter(d["body"]["notes"]))
    command(
        pilot,
        "merchant",
        d["version"],
        "correct",
        "notes:" + nid,
        "关注英国报价，尚未确定方案",
    )
    p.notes[0].text = "已确定方案"
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert len(d["body"]["notes"]) == 1
    assert d["body"]["notes"][nid]["text"] == "关注英国报价，尚未确定方案"


def test_failed_transport_review_is_isolated_with_bounded_calls(pilot):
    calls = []

    def respond(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(payload)
        _, p = proposal(pilot)
        p.notes.append(p.notes[0].model_copy(update={"text": "询问汽运"}))
        body = {"proposal": p.model_dump()}
        if "draft" in payload:
            body["checked"] = True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": dumps(body)}}
                ],
                "usage": {"total_tokens": 10},
            },
        )

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(respond)
    ) as client:
        run(pilot, "merchant", client)
        assert run(pilot, "merchant", client)["cached"]
    assert len(calls) == 3
    d = read(pilot, "merchant")
    assert d["body"]["quality_issues"]
    assert len(d["body"]["notes"]) == 1
    assert all(a["state"] == "proposed" for a in d["body"]["actions"].values())
    assert d["body"]["batches"]
    assert "汽运" not in dumps(d["body"])


def test_operating_rule_not_a_confirmation_and_obligation_survives_bad_note(pilot):
    from wechat_agent.workspace.quality import isolate_invalid_items
    from wechat_agent.workspace.schema import Decision
    from wechat_agent.workspace.views import details

    ctx, p = proposal(pilot)
    p.decisions = [Decision(key="other", text="件重以实际为准", evidence=p.evidence)]
    p.notes[0].text = "询问汽运"
    safe = isolate_invalid_items(p, ctx)
    d = commit(pilot, "merchant", safe, ctx, snapshot(pilot, "merchant"))
    assert not d["body"]["decisions"]
    aid = next(iter(d["body"]["actions"]))
    assert d["body"]["actions"][aid]["state"] == "proposed"
    command(pilot, "merchant", d["version"], "confirm_action", aid, True)
    assert details(pilot, "merchant")["today_action_ids"] == [aid]


def test_fulfillment_batch_stops_new_stocking_tasks(pilot):
    ctx, p = proposal(pilot)
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    p.batches[0].ref = next(iter(d["body"]["batches"]))
    p.batches[0].stage = "fulfillment"
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert all(a["state"] == "cancelled" for a in d["body"]["actions"].values())
    p.batches[0].stage = "preparing"
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert next(iter(d["body"]["batches"].values()))["stage"] == "fulfillment"


def test_post_shipment_only_suppresses_unbatched_tasks_and_questions(pilot):
    from wechat_agent.workspace.schema import Decision

    ctx, p = proposal(pilot)
    p.batches[0].stage = "fulfillment"
    p.actions[0].batch = None
    p.decisions = [
        Decision(
            key="other",
            text="确认件重",
            evidence=p.evidence,
            blocks_followup=True,
            impact="补充件重",
        )
    ]
    d = commit(pilot, "merchant", p, ctx, snapshot(pilot, "merchant"))
    assert not d["body"]["actions"]
    assert not d["body"]["decisions"]
