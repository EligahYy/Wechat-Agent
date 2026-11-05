import httpx
from fastapi.testclient import TestClient
from test_crm import setup_work_chat

from wechat_agent.collector import Collector
from wechat_agent.db import DB, now, uid
from wechat_agent.monitoring import snapshot
from wechat_agent.web import create_app


def factory(response):
    def create(db):
        return Collector(
            db,
            httpx.Client(
                base_url="http://127.0.0.1:9100",
                transport=httpx.MockTransport(response),
            ),
        )

    return create


def test_monitor_distinguishes_source_binding_disabled_background_and_stale_heartbeat(
    db,
):
    db.settings.source_account = db.settings.self_id = "account"
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "ready": True,
                "current_account": {"wxid": "account", "name": "工作昵称"},
                "cli_version": "0.7.4",
            },
        )

    db.heartbeat("collector", "running")
    db.heartbeat("worker", "running")
    with db.tx() as c:
        c.execute("UPDATE runtime SET updated_at='2020-01-01T00:00:00+00:00'")
    data = snapshot(db, factory(handler), True)
    assert data["checks"][1]["state"] == "ok"
    assert "工作昵称" in data["checks"][1]["detail"]
    assert data["checks"][2]["state"] == "warning"
    assert "较久" in data["checks"][2]["detail"]
    assert paths == ["/api/v1/health"]
    assert snapshot(db, factory(handler), False)["checks"][3]["state"] == "warning"


def test_monitor_failure_is_sanitized_and_does_not_make_model_request(db):
    def handler(request):
        raise httpx.ConnectError("sensitive transport details", request=request)

    data = snapshot(db, factory(handler), True)
    assert data["checks"][1]["state"] == "error"
    assert "sensitive" not in str(data)


def test_clear_pending_is_scoped_idempotent_and_preserves_resolved_items(db, record):
    setup_work_chat(db, record)
    with db.tx() as c:
        for account, status in (
            ("account", "pending"),
            ("account", "resolved"),
            ("other", "pending"),
        ):
            c.execute(
                "INSERT INTO crm_reviews(id,account_id,question,evidence,status,created_at) VALUES(?,?,?,?,?,?)",
                (uid(), account, status, "[]", status, now()),
            )
    app = create_app(db.settings)
    with TestClient(app) as client:
        assert client.post("/api/crm/reviews/clear", json={}).status_code == 401
        headers = {"Authorization": "Bearer " + db.token}
        result = client.post("/api/crm/reviews/clear", json={}, headers=headers)
        assert result.status_code == 200 and result.json()["cleared"] == 1
        assert (
            client.post("/api/crm/reviews/clear", json={}, headers=headers).json()[
                "cleared"
            ]
            == 0
        )
        assert client.get("/api/crm/reviews", headers=headers).json() == []
    assert len(db.rows("SELECT * FROM messages")) == 1
    assert len(db.rows("SELECT * FROM crm_reviews WHERE status='resolved'")) == 1
    assert (
        len(
            db.rows(
                "SELECT * FROM crm_reviews WHERE account_id='other' AND status='pending'"
            )
        )
        == 1
    )


def test_v7_upgrade_clears_existing_pending_only_once(db, record):
    setup_work_chat(db, record)
    with db.tx() as c:
        c.execute(
            "INSERT INTO crm_reviews(id,account_id,question,evidence,created_at) VALUES(?,?,?,?,?)",
            (uid(), "account", "旧问题", "[]", now()),
        )
        c.execute("PRAGMA user_version=7")
        c.execute("UPDATE conversations SET followup_source=0")
    upgraded = DB(db.settings)
    assert upgraded.rows("SELECT status FROM crm_reviews")[0]["status"] == "cleared"
    assert (
        upgraded.rows("SELECT followup_source FROM conversations")[0]["followup_source"]
        == 1
    )
    with upgraded.tx() as c:
        c.execute(
            "INSERT INTO crm_reviews(id,account_id,question,evidence,created_at) VALUES(?,?,?,?,?)",
            (uid(), "account", "新问题", "[]", now()),
        )
    assert (
        len(DB(db.settings).rows("SELECT * FROM crm_reviews WHERE status='pending'"))
        == 1
    )


def test_monitor_reports_authentication_failure_separately(db):
    data = snapshot(db, factory(lambda request: httpx.Response(401)), False)
    assert data["checks"][1]["state"] == "error"
    assert "WX_SOURCE_TOKEN" in data["checks"][1]["detail"]
