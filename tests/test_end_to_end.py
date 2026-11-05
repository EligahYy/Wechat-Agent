"""Source contract mock -> real storage -> model mock -> real authenticated UI API."""

import json

import httpx
from fastapi.testclient import TestClient

from wechat_agent.analysis import run_once
from wechat_agent.collector import Collector
from wechat_agent.services import allow_conversation, create_merchant, create_project
from wechat_agent.web import create_app


def test_source_to_review_to_confirmed_followup(db, monkeypatch):
    db.settings.source_account = "wx-self"
    db.settings.self_id = "wx-self"
    mid = create_merchant(db, "示例商家")
    pid = create_project(db, mid, "第一批", "美国")
    cid = allow_conversation(
        db,
        "wx_cli",
        "wx-self",
        "room@chatroom",
        "三方群",
        "group",
        mid,
        pid,
        True,
        followup_source=True,
    )

    def source(req):
        if req.url.path.endswith("/health"):
            return httpx.Response(
                200, json={"ready": True, "current_account": {"wxid": "wx-self"}}
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "talker": "room@chatroom",
                        "server_id": 123,
                        "sender": "provider-id",
                        "msg_type": 1,
                        "create_time": 100,
                        "content": {"Text": "我是头程服务商，明天确认附加费。"},
                    }
                ],
                "paging": {"has_more": False},
                "stats": {"skipped": 0, "shard_warnings": []},
            },
        )

    collector = Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(source)
        ),
    )
    assert (
        collector.sync_window(
            db.rows("SELECT * FROM conversations WHERE id=?", (cid,))[0], 90, 110
        )["inserted"]
        == 1
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key")
    response = {
        "schema_version": 1,
        "suggestions": [
            {
                "kind": "task_create",
                "summary": "服务商确认本批附加费",
                "responsible_party": "service_provider",
                "due_text": "明天",
                "evidence_refs": ["E001"],
            }
        ],
    }
    model = httpx.Client(
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(response)},
                        }
                    ],
                    "usage": {"total_tokens": 100},
                },
            )
        ),
    )
    assert run_once(db, model)
    app = create_app(db.settings)
    web = TestClient(app)
    h = {"Authorization": "Bearer " + db.token}
    state = web.get("/api/state", headers=h).json()
    sid = state["suggestions"][0]["id"]
    tid = web.post(f"/api/suggestions/{sid}/accept", json={}, headers=h).json()["id"]
    task = web.get("/api/state", headers=h).json()["tasks"][0]
    assert task["party"] == "service_provider" and task["state"] == "waiting_external"
    assert (
        web.post(
            "/api/touchpoints",
            json={
                "merchant_id": mid,
                "project_id": pid,
                "outcome": "人工已向服务商核实，明日再确认",
            },
            headers=h,
        ).status_code
        == 200
    )
    assert (
        web.post(
            f"/api/tasks/{tid}/transition",
            json={
                "state": "snoozed",
                "version": 1,
                "due_at": "2026-11-05T09:00:00+08:00",
            },
            headers=h,
        ).status_code
        == 200
    )
    assert web.get("/api/state", headers=h).json()["projects"][0]["stage"] == "needs"
    assert len(db.rows("SELECT * FROM touchpoints")) == 1
