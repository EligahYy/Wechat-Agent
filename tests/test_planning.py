import json
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from wechat_agent.analysis import budget_state, run_once
from wechat_agent.collector import Collector
from wechat_agent.config import Settings
from wechat_agent.crm import configure, schedule
from wechat_agent.db import dumps, now, uid
from wechat_agent.ingestion import ingest
from wechat_agent.planning import BATCH, fingerprint
from wechat_agent.progress import overview
from wechat_agent.services import allow_conversation
from wechat_agent.web import create_app


def corpus(db, record, recent=160, history=100):
    db.settings.source_account = db.settings.self_id = "account"
    cid = allow_conversation(
        db,
        "wx_cli",
        "account",
        "person",
        "商家昵称",
        "private",
        None,
        None,
        False,
        followup_source=True,
    )
    stamp = datetime.now(UTC)
    rows = [
        record
        | {
            "source": "wx_cli",
            "conversation_id": "person",
            "conversation_type": "private",
            "sender_id": "person",
            "source_id": str(i),
            "text": "请确认欧洲备货报价条件 " + str(i),
            "event_time": (
                stamp - timedelta(days=1 if i >= history else 100, seconds=i)
            ).isoformat(),
        }
        for i in range(recent + history)
    ]
    ingest(db, rows, analyze=False)
    return cid, rows


def empty_model(observe=None, status=200):
    def handler(request):
        if observe:
            observe(json.loads(request.content))
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": 2,
                                    "people": [],
                                    "actions": [],
                                    "ambiguities": [],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 100},
            },
        )

    return httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)
    )


def test_recent_fifteen_days_is_bounded_and_history_waits(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    corpus(db, record)
    configure(db, True)
    jobs = db.rows("SELECT * FROM jobs WHERE status='queued'")
    assert len(jobs) == BATCH
    assert all(json.loads(j["payload"])["scope"] == "recent" for j in jobs)
    assert db.rows("SELECT * FROM jobs WHERE status='deferred_history'")
    progress = overview(db)
    assert progress["scope"]["recent"]["total"] == 160
    assert progress["scope"]["history"]["total"] == 100
    calls = []
    assert run_once(db, empty_model(calls.append))
    schedule(db)
    assert overview(db)["scope"]["recent"]["analyzed"] > 0
    primary_times = [
        m["time"] for m in json.loads(calls[0]["messages"][1]["content"])["messages"]
    ]
    assert len(primary_times) <= 24  # two earlier and six later context messages
    assert (
        len(
            db.rows(
                "SELECT * FROM jobs WHERE status IN ('queued','running','retry_wait')"
            )
        )
        <= BATCH
    )


def test_history_only_promotes_one_after_recent_and_reserves_budget(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    corpus(db, record, recent=1, history=50)
    configure(db, True)
    assert run_once(db, empty_model())
    schedule(db)
    assert len(db.rows("SELECT * FROM jobs WHERE status='queued'")) == 1
    assert (
        json.loads(
            db.rows("SELECT payload FROM jobs WHERE status='queued'")[0]["payload"]
        )["scope"]
        == "history"
    )
    with db.tx() as c:
        c.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
            (uid(), None, budget_state(db)["day"], 81000, 81000, "reported", now()),
        )
        c.execute("UPDATE jobs SET status='deferred_history' WHERE status='queued'")
    schedule(db)
    assert not db.rows("SELECT * FROM jobs WHERE status='queued'")


def test_budget_gate_stops_walking_entire_queue(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    corpus(db, record, recent=160, history=20)
    configure(db, True, budget=1000)
    sent = []
    assert run_once(db, empty_model(sent.append))
    assert not run_once(db, empty_model(sent.append))
    assert not sent
    assert len(db.rows("SELECT * FROM jobs WHERE status='blocked_budget'")) == 1
    assert len(db.rows("SELECT * FROM jobs WHERE status='queued'")) == BATCH - 1
    assert overview(db)["gate"]["reason"] == "blocked_budget"


def test_rejected_request_releases_reservation_and_has_no_false_spend(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    corpus(db, record, recent=1, history=0)
    configure(db, True)
    assert run_once(db, empty_model(status=401))
    budget = budget_state(db)
    assert budget["reported"] == budget["uncertain"] == 0
    assert db.rows("SELECT status FROM usage")[0]["status"] == "request_rejected"
    assert overview(db)["gate"]["reason"] == "blocked_credentials"


def test_completed_legacy_unit_is_not_rebilled_when_pending_queue_replaced(db, record):
    cid, _ = corpus(db, record, recent=2, history=0)
    rows = db.rows("SELECT * FROM messages ORDER BY event_time,id")
    with db.tx() as c:
        c.execute(
            "INSERT INTO crm_policies(account_id,enabled) VALUES(?,1)", ("account",)
        )
        c.execute("UPDATE conversations SET egress=1")
        p = {
            "engine": "crm_v2",
            "conversation_id": cid,
            "message_ids": [r["id"] for r in rows],
            "policy_version": 1,
        }
        c.execute(
            "INSERT INTO jobs(id,dedup_key,payload,status,available_at,created_at) VALUES(?,?,?,?,?,?)",
            (
                uid(),
                fingerprint(cid, rows, {}, 1, legacy=True),
                dumps(p),
                "succeeded",
                now(),
                now(),
            ),
        )
        c.execute(
            "INSERT INTO jobs(id,dedup_key,payload,status,available_at,created_at) VALUES(?,?,?,?,?,?)",
            (uid(), "obsolete-pending", dumps(p), "blocked_budget", now(), now()),
        )
    schedule(db)
    assert overview(db)["scope"]["recent"]["analyzed"] == 2
    assert not db.rows("SELECT * FROM jobs WHERE status='queued'")
    assert (
        db.rows("SELECT status FROM jobs WHERE dedup_key='obsolete-pending'")[0][
            "status"
        ]
        == "superseded"
    )


def test_account_nickname_persists_after_probe_and_restart(db):
    db.settings.bind_source("account")
    source = Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100",
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    json={
                        "ready": True,
                        "current_account": {"wxid": "account", "name": "运营昵称"},
                    },
                )
            ),
        ),
    )
    assert source.probe()["account_name"] == "运营昵称"
    assert Settings(data_dir=db.settings.data_dir).prepare().source_name == "运营昵称"
    source.client.close()


def test_progress_api_is_authenticated_paginated_and_does_not_show_chat_text(
    db, record
):
    corpus(db, record, recent=160, history=20)
    configure(db, True)
    with TestClient(create_app(db.settings)) as web:
        assert web.get("/api/analysis/progress").status_code == 401
        h = {"Authorization": "Bearer " + db.token}
        data = web.get("/api/analysis/progress", headers=h).json()
        assert data["recent_days"] == 15 and data["budget"]["limit"] == 100000
        jobs = web.get("/api/analysis/jobs?scope=recent&page=1", headers=h).json()
        assert jobs["total"] > 0 and all(j["scope"] == "recent" for j in jobs["items"])
        assert "请确认欧洲备货报价条件" not in json.dumps(jobs, ensure_ascii=False)
        assert web.get("/api/analysis/jobs?scope=invalid", headers=h).status_code == 422


def test_uncertain_budget_requires_confirmed_bill_and_keeps_raw_usage(db, record):
    corpus(db, record, recent=1, history=0)
    configure(db, True)
    day = budget_state(db)["day"]
    with db.tx() as c:
        c.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
            (
                uid(),
                None,
                day,
                100000,
                None,
                "unknown",
                (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
            ),
        )
    assert budget_state(db)["remaining"] == 0
    with TestClient(create_app(db.settings)) as web:
        h = {"Authorization": "Bearer " + db.token}
        assert (
            web.post(
                "/api/analysis/budget/reconcile",
                json={"confirmed_tokens": 0},
                headers=h,
            ).status_code
            == 422
        )
        assert (
            web.post(
                "/api/analysis/budget/reconcile",
                json={"confirmed_tokens": 100, "confirm_billing": True},
                headers=h,
            ).status_code
            == 200
        )
    assert budget_state(db)["reported"] == 100
    assert budget_state(db)["remaining"] == 99900
    assert db.rows("SELECT actual,reserved FROM usage")[0] == {
        "actual": None,
        "reserved": 100000,
    }


def test_consecutive_model_failures_pause_queue_instead_of_burning_every_job(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    corpus(db, record, recent=160, history=0)
    configure(db, True)
    calls = []
    model = empty_model(calls.append, status=500)
    assert run_once(db, model)
    assert run_once(db, model)
    assert not run_once(db, model)
    assert len(calls) == 2
    assert overview(db)["gate"]["reason"] == "consecutive_errors"


def test_noise_filter_does_not_charge_but_mixed_context_is_kept(db, record):
    cid, rows = corpus(db, record, recent=1, history=0)
    ingest(db, [rows[0] | {"text": "收到"}], analyze=False)
    configure(db, True)
    assert not db.rows("SELECT * FROM jobs WHERE status='queued'")
    assert overview(db)["scope"]["recent"]["filtered"] == 1
    assert budget_state(db)["calls"] == 0


def test_history_budget_hold_preserves_capacity_for_new_recent_messages(
    db, record, monkeypatch
):
    from wechat_agent.planning import gate

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, rows = corpus(db, record, recent=1, history=50)
    configure(db, True)
    run_once(db, empty_model())
    with db.tx() as c:
        c.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
            (uid(), None, budget_state(db)["day"], 79000, 79000, "reported", now()),
        )
    schedule(db)
    sent = []
    assert run_once(db, empty_model(sent.append))
    assert not sent and gate(db, history=True) and not gate(db)
    schedule(db)
    assert not db.rows("SELECT * FROM jobs WHERE status='queued'")
    ingest(
        db,
        [
            rows[-1]
            | {
                "source_id": "new-incoming",
                "event_time": datetime.now(UTC).isoformat(),
                "text": "新增欧洲备货需求，请确认费用。",
            }
        ],
    )
    assert run_once(db, empty_model(sent.append))
    assert len(sent) == 1


def test_safe_diagnostics_uses_recorded_failure_and_excludes_sensitive_data(
    db, record, monkeypatch
):
    from wechat_agent.diagnostics import snapshot

    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-print-secret")
    corpus(db, record, recent=1, history=0)
    configure(db, True)
    assert run_once(db, empty_model(status=402))
    job = db.rows("SELECT id FROM jobs WHERE status='retry_wait'")[0]
    # A subsequent retry can replace the job's error; historical diagnoses must
    # still reflect the recorded failed request rather than the mutable job row.
    with db.tx() as c:
        c.execute("UPDATE jobs SET error=NULL WHERE id=?", (job["id"],))
    result = snapshot(db)
    assert result["recent_errors"][0]["code"] == "HTTP_402"
    assert "余额不足" in result["recent_errors"][0]["title"]
    encoded = json.dumps(result, ensure_ascii=False)
    assert "must-not-print-secret" not in encoded
    assert "商家昵称" not in encoded and "请确认欧洲备货" not in encoded
    assert "account_id" not in encoded


def test_diagnose_command_is_local_only(db, record, monkeypatch, capsys):
    from wechat_agent.cli import main

    corpus(db, record, recent=1, history=0)
    monkeypatch.setattr(
        "sys.argv",
        ["wechat-agent", "--data-dir", str(db.settings.data_dir), "diagnose"],
    )
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["model"] and report["recent_errors"] == []


def test_usage_chart_has_seven_ordered_days_and_matches_reconciled_budget(db, record):
    corpus(db, record, recent=1, history=0)
    configure(db, True)
    today = budget_state(db)["day"]
    with db.tx() as c:
        c.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
            (uid(), None, today, 98000, None, "unknown", now()),
        )
        rowid = c.execute("SELECT MAX(rowid) FROM usage").fetchone()[0]
        db.event(
            c,
            "local-budget:" + today,
            "budget_reconciled",
            {"confirmed_tokens": 17000, "through_rowid": rowid},
        )
        c.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
            (uid(), None, today, 1000, 600, "reported", now()),
        )
    data = overview(db)
    days = data["daily_usage"]
    assert len(days) == 7 and days[-1]["day"] == today
    assert all(days[i]["day"] < days[i + 1]["day"] for i in range(6))
    assert all(d["reported"] == d["uncertain"] == d["calls"] == 0 for d in days[:-1])
    assert days[-1]["reported"] == data["budget"]["reported"] == 17600
    assert days[-1]["uncertain"] == data["budget"]["uncertain"] == 0
    assert days[-1]["raw_uncertain"] == 98000 and days[-1]["reconciled"]
    assert days[-1]["calls"] == 2
