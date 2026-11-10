import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from wechat_agent.analysis import run_once
from wechat_agent.crm import (
    configure,
    customer_details,
    overview,
    schedule,
    stable_actor,
    transition,
)
from wechat_agent.ingestion import ingest
from wechat_agent.message_value import classify
from wechat_agent.services import Conflict, allow_conversation
from wechat_agent.web import create_app


def setup_work_chat(db, record, kind="private", chat_id="merchant"):
    if kind == "group" and chat_id == "merchant":
        chat_id = "merchant-group@chatroom"
    db.settings.source_account = db.settings.self_id = "account"
    cid = allow_conversation(
        db,
        "wx_cli",
        "account",
        chat_id,
        "客户甲",
        kind,
        None,
        None,
        False,
        followup_source=True,
    )
    row = record | {
        "source": "wx_cli",
        "conversation_id": chat_id,
        "conversation_type": kind,
        "sender_id": "merchant",
        "event_time": datetime.now(UTC).isoformat(),
        "text": "我这批美国普货约3方，请向物流确认附加费。",
    }
    ingest(db, [row])
    return cid, row


def response(db, operation="create", refs=None, key="确认附加费"):
    actor = stable_actor("account", "merchant")
    return {
        "schema_version": 2,
        "people": [
            {
                "actor_ref": actor,
                "role": "merchant",
                "facts": [
                    {
                        "field": "market",
                        "value": "美国",
                        "evidence_refs": refs or ["E001"],
                    }
                ],
                "evidence_refs": refs or ["E001"],
            }
        ],
        "actions": [
            {
                "customer_ref": actor,
                "contact_ref": actor,
                "action_key": key,
                "operation": operation,
                "summary": "确认本批附加费",
                "reason": "商家正在等待报价条件",
                "opportunity": "美国本批普通货",
                "stage": "quoting",
                "party": "self",
                "evidence_refs": refs or ["E001"],
            }
        ],
        "ambiguities": [],
    }


def model(content, observe=None):
    def handle(req):
        if observe:
            observe(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(content)},
                    }
                ],
                "usage": {"total_tokens": 100},
            },
        )

    return httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(handle)
    )


def drain(db, client):
    for _ in range(20):
        if not run_once(db, client):
            return
    raise AssertionError("worker did not drain")


def test_empty_business_database_automatically_builds_evidenced_customer_and_plan(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    setup_work_chat(db, record)
    assert not db.rows("SELECT * FROM merchants") and not db.rows(
        "SELECT * FROM projects"
    )
    configure(db, True)
    sent = []
    drain(db, model(response(db), sent.append))
    assert db.rows(
        "SELECT status FROM jobs WHERE json_extract(payload,'$.engine')='crm_v2'"
    ) == [{"status": "succeeded"}]
    customers = db.rows("SELECT * FROM crm_customers")
    assert len(customers) == 1 and customers[0]["name"] == "客户甲"
    assert len(db.rows("SELECT * FROM crm_plans")) == 1
    assert len(db.rows("SELECT * FROM crm_actions")) == 1
    detail = customer_details(db, customers[0]["id"])
    assert detail["facts"][0]["sources"][0]["text"].startswith("我这批美国")
    assert detail["facts"][0]["evidence_valid"]
    assert "merchant" not in json.dumps(
        sent[0]["messages"][1]["content"]
    )  # local identity not sent
    assert not db.rows("SELECT * FROM suggestions")
    assert schedule(db) == 0


def test_new_reply_closes_existing_task_without_manual_acceptance(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db)))
    original = db.rows("SELECT * FROM crm_actions")[0]
    ingest(
        db,
        [
            row
            | {
                "source_id": "2",
                "text": "附加费已确认，含派送费。",
                "event_time": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            }
        ],
    )
    seen = []
    drain(db, model(response(db, "complete", ["E002"]), seen.append))
    assert len(db.rows("SELECT * FROM crm_actions")) == 1
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "done"
    assert (
        original["action_key"]
        in json.loads(seen[-1]["messages"][1]["content"])["known_actions"][0][
            "action_key"
        ]
    )


def test_old_commitment_does_not_flood_today_and_manual_close_survives_rerun(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    ingest(
        db,
        [row | {"event_time": (datetime.now(UTC) - timedelta(days=100)).isoformat()}],
    )
    configure(db, True)
    drain(db, model(response(db)))
    action = db.rows("SELECT * FROM crm_actions")[0]
    assert action["state"] == "historical_unresolved"
    assert not overview(db)["actions"]
    transition(db, action["id"], "cancelled", action["version"])
    with pytest.raises(Conflict):
        transition(db, action["id"], "open", action["version"])
    ingest(db, [row | {"source_id": "2"}])
    drain(db, model(response(db)))
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "cancelled"


def test_invalid_identity_evidence_and_revocation_do_not_pollute_crm(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    setup_work_chat(db, record)
    configure(db, True)
    invalid = response(db)
    invalid["people"][0]["actor_ref"] = "invented-identity"
    run_once(db, model(invalid))
    assert not db.rows("SELECT * FROM crm_customers")
    schedule(db, retry=True)
    run_once(db, model(response(db), lambda _: configure(db, False)))
    assert not db.rows("SELECT * FROM crm_customers")
    assert not overview(db)["actions"]


def test_cross_private_and_group_identity_and_same_name_isolation(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    allow_conversation(
        db,
        "wx_cli",
        "account",
        "room@chatroom",
        "三方群",
        "group",
        None,
        None,
        False,
        followup_source=True,
    )
    ingest(
        db,
        [
            row
            | {
                "conversation_id": "room@chatroom",
                "conversation_type": "group",
                "source_id": "2",
            }
        ],
    )
    configure(db, True)
    drain(db, model(response(db)))
    assert len(db.rows("SELECT * FROM crm_customers")) == 1
    customer = db.rows("SELECT * FROM crm_customers")[0]
    assert len(customer_details(db, customer["id"])["messages"]) == 2
    assert len(db.rows("SELECT * FROM crm_actions")) == 1


def test_message_filter_retains_negation_numbers_dates_and_media():
    def row(text, kind="text"):
        return {"text": text, "type": kind}

    assert (
        classify(row("收到，谢谢"))["value"] == "candidate"
    )  # conservative exact matches
    for text in ["收到", "你好", "OK！", "👍", ""]:
        assert classify(row(text))["value"] == "noise"
    for text in [
        "不需要了",
        "下周三",
        "3方",
        "好的，月底再联系",
        "费用含派送吗？",
        "报价表",
    ]:
        assert classify(row(text))["value"] == "candidate"
    assert classify(row("[图片]", "3"))["value"] == "attachment"


def test_crm_http_auth_and_versioned_action_flow(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    setup_work_chat(db, record)
    app = create_app(db.settings)
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + db.token}
        assert client.get("/api/crm").status_code == 401
        assert (
            client.post(
                "/api/crm/configure", json={"enabled": True}, headers=h
            ).status_code
            == 200
        )
        drain(db, model(response(db)))
        data = client.get("/api/crm", headers=h).json()
        assert data["customers_count"] == 1
        actions = data["all_actions"]
        task = actions[0]
        assert client.get(
            "/api/crm/actions/" + task["id"] + "/evidence", headers=h
        ).json()["messages"]
        assert (
            client.post(
                "/api/crm/actions/" + task["id"] + "/transition",
                json={
                    "state": "snoozed",
                    "version": task["version"],
                    "due_date": "2030-01-01",
                    "note": "用户改期",
                },
                headers=h,
            ).status_code
            == 200
        )
        assert db.rows("SELECT * FROM crm_actions")[0]["locked"] == 1
        assert (
            client.post(
                "/api/crm/actions/" + task["id"] + "/transition",
                json={"state": "done", "version": task["version"]},
                headers=h,
            ).status_code
            == 409
        )


def test_authorization_and_budget_edit_are_idempotent(db, record):
    setup_work_chat(db, record)
    configure(db, True)
    count = len(
        db.rows("SELECT * FROM jobs WHERE json_extract(payload,'$.engine')='crm_v2'")
    )
    configure(db, True, budget=200000)
    assert (
        len(
            db.rows(
                "SELECT * FROM jobs WHERE json_extract(payload,'$.engine')='crm_v2'"
            )
        )
        == count
    )


def test_source_revision_invalidates_visible_fact_and_draft_evidence(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db)))
    customer = db.rows("SELECT * FROM crm_customers")[0]
    ingest(db, [row | {"text": "改为欧洲线路"}])
    assert not customer_details(db, customer["id"])["facts"][0]["evidence_valid"]
    assert not overview(db)["all_actions"][0]["evidence_valid"]


def test_actual_outgoing_contact_is_recorded_but_does_not_complete_task(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db)))
    ingest(
        db,
        [
            row
            | {
                "source_id": "2",
                "sender_id": "account",
                "direction": "outgoing",
                "text": "我去问问服务商。",
                "event_time": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            }
        ],
    )
    assert len(db.rows("SELECT * FROM events WHERE kind='crm_contact'")) == 1
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "open"
    assert not overview(db)[
        "actions"
    ]  # non-explicit suggestions respect contact cool-down
    assert schedule(db) == 0


def test_relative_dates_are_based_on_original_message():
    from wechat_agent.followup_dates import due_date

    assert due_date("明天", "2024-01-01T22:00:00+08:00") == "2024-01-02"
    assert due_date("下周三", "2024-01-01T22:00:00+08:00") == "2024-01-10"
    assert due_date("周五", "2024-01-06T09:00:00+08:00") == "2024-01-12"
    assert due_date("以后再说", "2024-01-01T22:00:00+08:00") is None


def test_v5_migration_backs_up_and_keeps_manual_tasks(db, chat):
    from wechat_agent.db import DB, now

    merchant = db.rows("SELECT * FROM merchants")[0]
    with db.tx() as c:
        c.execute(
            "INSERT INTO tasks(id,merchant_id,summary,party,state,created_at) VALUES('old-task',?,'人工事项','self','open',?)",
            (merchant["id"], now()),
        )
    c = db.connect()
    c.execute("PRAGMA foreign_keys=OFF")
    for table in [
        "crm_reviews",
        "crm_actions",
        "crm_plans",
        "crm_facts",
        "crm_customers",
        "crm_contacts",
        "crm_policies",
    ]:
        c.execute("DROP TABLE " + table)
    c.execute("PRAGMA user_version=5")
    c.commit()
    c.close()
    migrated = DB(db.settings)
    assert migrated.rows("SELECT * FROM crm_actions")[0]["id"] == "old-task"
    assert migrated.rows("SELECT * FROM crm_customers")[0]["name"] == merchant["name"]
    assert list(db.settings.data_dir.glob("pre-v6-*.sqlite3"))
    assert not migrated.rows("PRAGMA foreign_key_check")


def test_unified_runtime_awaits_account_and_shuts_down_cleanly(db):
    app = create_app(db.settings, background=True)
    with TestClient(app):
        assert app.state.background
    assert (
        db.rows("SELECT * FROM runtime WHERE name='collector'")[0]["status"]
        == "awaiting_account"
    )


def test_manual_fact_correction_is_locked_and_only_related_input_requeues(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db)))
    app = create_app(db.settings)
    fact = db.rows("SELECT * FROM crm_facts")[0]
    with TestClient(app) as web:
        result = web.post(
            "/api/crm/facts/" + fact["id"],
            json={"value": "加拿大"},
            headers={"Authorization": "Bearer " + db.token},
        )
        assert result.status_code == 200
    drain(db, model(response(db)))
    stored = db.rows("SELECT * FROM crm_facts")
    assert len(stored) == 1 and stored[0]["value"] == "加拿大" and stored[0]["locked"]
    assert schedule(db) == 0


def test_excluded_conversation_stays_excluded_after_budget_edit_and_resume(db, record):
    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    with TestClient(create_app(db.settings)) as web:
        h = {"Authorization": "Bearer " + db.token}
        assert (
            web.post(
                "/api/crm/conversations/" + cid + "/policy",
                json={"enabled": False},
                headers=h,
            ).status_code
            == 200
        )
    configure(db, True, budget=200000)
    assert (
        db.rows("SELECT egress FROM conversations WHERE id=?", (cid,))[0]["egress"] == 0
    )
    configure(db, False)
    configure(db, True)
    assert (
        db.rows("SELECT egress FROM conversations WHERE id=?", (cid,))[0]["egress"] == 0
    )


def test_draft_is_cached_and_does_not_record_contact_or_complete_action(
    db, record, monkeypatch
):
    import wechat_agent.web as web_module
    from wechat_agent.analysis import call_model

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db)))
    task = db.rows("SELECT * FROM crm_actions")[0]
    calls = []
    client = model(
        {"text": "您好，这批货的附加费我再确认一下。", "evidence_refs": ["E001"]},
        calls.append,
    )
    monkeypatch.setattr(
        web_module,
        "call_model",
        lambda database, payload, **kw: call_model(
            database, payload, client=client, **kw
        ),
    )
    with TestClient(create_app(db.settings)) as web:
        h = {"Authorization": "Bearer " + db.token}
        for _ in range(2):
            assert (
                web.post(
                    "/api/crm/actions/" + task["id"] + "/draft", json={}, headers=h
                ).status_code
                == 200
            )
    assert len(calls) == 1
    assert not db.rows("SELECT * FROM events WHERE kind='crm_contact'")
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "open"


def test_runtime_prevents_two_owners_of_same_database(db):
    from wechat_agent.runtime import Runtime

    first, second = Runtime(db), Runtime(db)
    first.start()
    try:
        with pytest.raises(RuntimeError):
            second.start()
    finally:
        first.close()


def test_recent_cancellation_tombstone_prevents_older_history_resurrecting_task(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _, row = setup_work_chat(db, record)
    configure(db, True)
    drain(db, model(response(db, "cancel")))
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "cancelled"
    ingest(
        db,
        [
            row
            | {
                "source_id": "older",
                "event_time": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
            }
        ],
    )
    drain(db, model(response(db, "create", ["E001"])))
    assert len(db.rows("SELECT * FROM crm_actions")) == 1
    assert db.rows("SELECT * FROM crm_actions")[0]["state"] == "cancelled"
