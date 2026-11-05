"""Follow-up eligibility never implicitly follows archive or model consent."""

import pytest
from fastapi.testclient import TestClient
from test_crm import model, response, setup_work_chat

from wechat_agent.analysis import Blocked, context, run_once
from wechat_agent.crm import configure, overview, schedule
from wechat_agent.db import DB
from wechat_agent.ingestion import ingest
from wechat_agent.services import allow_conversation
from wechat_agent.source_scope import counts, list_sources, set_sources
from wechat_agent.web import create_app


def test_archive_and_account_consent_do_not_select_new_chats(db, record):
    cid, row = setup_work_chat(db, record)
    with db.tx() as c:
        c.execute("UPDATE conversations SET followup_source=0")
    configure(db, True)
    assert counts(db) == {"total": 1, "selected": 0, "archive_only": 1}
    assert schedule(db) == 0
    with pytest.raises(Blocked):
        context(db, cid)
    assert not run_once(db)
    assert len(db.rows("SELECT * FROM messages")) == 1
    other = allow_conversation(
        db, "wx_cli", "account", "coworker", "同事", "private", egress=True
    )
    ingest(
        db,
        [
            row
            | {"conversation_id": "coworker", "sender_id": "coworker", "source_id": "2"}
        ],
    )
    assert not db.rows(
        "SELECT followup_source FROM conversations WHERE id=?", (other,)
    )[0]["followup_source"]
    assert schedule(db) == 0


def test_select_revoke_reselect_preserves_results_without_rebilling(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    set_sources(db, [cid], False)
    assert not run_once(db)
    assert db.rows("SELECT * FROM messages")
    set_sources(db, [cid], True)
    assert run_once(db, model(response(db)))
    assert len(overview(db)["all_actions"]) == 1
    assert overview(db)["all_actions"][0]["source_eligible"]
    set_sources(db, [cid], False)
    data = overview(db)
    assert not data["actions"] and not data["all_actions"][0]["source_eligible"]
    assert len(db.rows("SELECT * FROM crm_customers")) == 1
    assert len(db.rows("SELECT * FROM usage")) == 1
    set_sources(db, [cid], True)
    assert not run_once(db, model(response(db)))
    assert len(overview(db)["all_actions"]) == 1
    assert overview(db)["all_actions"][0]["source_eligible"]
    assert len(db.rows("SELECT * FROM usage")) == 1


def test_revocation_during_model_request_does_not_apply_response(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    run_once(db, model(response(db), lambda _: set_sources(db, [cid], False)))
    assert not db.rows("SELECT * FROM crm_customers")
    assert not db.rows("SELECT * FROM crm_actions")
    assert db.rows("SELECT * FROM usage")  # sent requests retain their actual spend


def test_excluded_chat_cannot_provide_customer_memory(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cid, row = setup_work_chat(db, record)
    configure(db, True)
    run_once(db, model(response(db)))
    set_sources(db, [cid], False)
    other = allow_conversation(
        db,
        "wx_cli",
        "account",
        "merchant-group@chatroom",
        "三方群",
        "group",
        egress=True,
    )
    ingest(
        db,
        [
            row
            | {
                "conversation_id": "merchant-group@chatroom",
                "conversation_type": "group",
                "source_id": "2",
            }
        ],
    )
    set_sources(db, [other], True)
    _, _, payload, _ = context(db, other)
    assert not payload["customer_memory"] and not payload["known_actions"]


def test_batch_selection_is_atomic_and_account_scoped(db, record):
    cid, _ = setup_work_chat(db, record)
    foreign = allow_conversation(
        db, "wx_cli", "foreign", "person", "其他账号", "private"
    )
    with pytest.raises(ValueError):
        set_sources(db, [cid, foreign], False)
    assert counts(db)["selected"] == 1
    for ids, enabled in [([], True), ([cid], "false"), ([cid] * 501, True)]:
        with pytest.raises(ValueError):
            set_sources(db, ids, enabled)
    result = list_sources(db, q="客户", kind="private", scope="customer")
    assert result["total"] == 1 and result["items"][0]["id"] == cid
    assert not list_sources(db, kind="group")["items"]
    with pytest.raises(ValueError):
        list_sources(db, page=0)


def test_migration_preserves_archive_and_requires_explicit_whitelist(db, record):
    setup_work_chat(db, record)
    configure(db, True)
    with db.tx() as c:
        c.execute("ALTER TABLE conversations DROP COLUMN followup_source")
        c.execute("PRAGMA user_version=6")
    migrated = DB(db.settings)
    assert counts(migrated)["selected"] == 0
    assert migrated.rows("SELECT status FROM jobs")[0]["status"] == "excluded_source"
    assert len(migrated.rows("SELECT * FROM messages")) == 1
    backups = list(db.settings.data_dir.glob("pre-v7-*.sqlite3"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600


def test_whitelist_api_requires_auth_and_does_not_leak_messages(db, record):
    cid, _ = setup_work_chat(db, record)
    app = create_app(db.settings)
    with TestClient(app) as client:
        assert client.get("/api/crm/followup-sources").status_code == 401
        headers = {"Authorization": "Bearer " + db.token}
        data = client.get("/api/crm/followup-sources", headers=headers).json()
        assert "附加费" not in str(data)
        r = client.post(
            "/api/crm/followup-sources",
            json={"conversation_ids": [cid], "enabled": False},
            headers=headers,
        )
        assert r.status_code == 200 and r.json()["counts"]["selected"] == 0


def test_rediscovery_preserves_selection_and_new_sessions_stay_archive_only(db, record):
    from wechat_agent.archive import register

    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    register(
        db,
        [
            {
                "source_id": "merchant",
                "title": "更新昵称",
                "kind": "private",
                "excluded": False,
            },
            {
                "source_id": "coworkers@chatroom",
                "title": "同事群",
                "kind": "group",
                "excluded": False,
            },
        ],
        1793890000,
    )
    assert counts(db) == {"total": 2, "selected": 1, "archive_only": 1}
    assert (
        db.rows("SELECT title FROM conversations WHERE id=?", (cid,))[0]["title"]
        == "更新昵称"
    )
    with pytest.raises(Blocked):
        other = list_sources(db, kind="group")["items"][0]["id"]
        context(db, other)
