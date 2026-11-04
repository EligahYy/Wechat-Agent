from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from wechat_agent.collector import Collector
from wechat_agent.config import Settings
from wechat_agent.web import create_app


def source_response(request):
    if request.url.path.endswith("/health"):
        return httpx.Response(
            200,
            json={
                "ready": True,
                "cli_version": "test-build",
                "current_account": {"wxid": "work-account", "name": "工作小号"},
            },
        )
    if request.url.path.endswith("/sessions"):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "username": "group-a@chatroom",
                        "display_name": "商家 A 三方群",
                        "summary": "不应传到前端的摘要",
                    },
                    {"username": "private-person", "display_name": "私人联系人"},
                    {"username": "group-b@chatroom", "display_name": "商家 B 三方群"},
                ],
                "paging": {"has_more": False},
            },
        )
    if request.url.path.endswith("/messages"):
        group = request.url.params["contact"]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "talker": group,
                        "server_id": "100",
                        "sender": "merchant",
                        "msg_type": 1,
                        "create_time": int(datetime.now(UTC).timestamp()),
                        "content": {"Text": "请确认这批头程报价。"},
                    }
                ],
                "paging": {"has_more": False},
                "stats": {},
            },
        )
    return httpx.Response(404)


def setup(tmp_path):
    def factory(db):
        return Collector(
            db,
            httpx.Client(
                base_url="http://127.0.0.1:9100",
                transport=httpx.MockTransport(source_response),
            ),
        )

    app = create_app(Settings(data_dir=tmp_path), source_factory=factory)
    return app, TestClient(app), {"Authorization": "Bearer " + app.state.db.token}


def test_probe_bind_groups_and_two_group_trial_are_local_only(tmp_path):
    app, client, headers = setup(tmp_path)
    probe = client.post("/api/source/probe", json={}, headers=headers)
    assert probe.json()["account_id"] == "work-account" and not probe.json()["bound"]
    assert (
        client.post("/api/source/groups", json={}, headers=headers).status_code == 422
    )
    assert (
        client.post(
            "/api/source/bind", json={"account_id": "wrong-account"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/source/bind", json={"account_id": "work-account"}, headers=headers
        ).status_code
        == 200
    )
    groups = client.post("/api/source/groups", json={}, headers=headers).json()[
        "groups"
    ]
    assert (
        len(groups) == 2
        and "私人联系人" not in str(groups)
        and "摘要" not in str(groups)
    )
    assert not app.state.db.rows("SELECT * FROM messages")
    result = client.post("/api/source/pilot", json={"groups": groups}, headers=headers)
    assert result.status_code == 200 and result.json()["egress"] is False
    assert [r["inserted"] for r in result.json()["results"]] == [1, 1]
    assert len(app.state.db.rows("SELECT * FROM messages")) == 2
    assert all(
        c["egress"] == 0 for c in app.state.db.rows("SELECT * FROM conversations")
    )
    assert (
        len(
            client.post(
                "/api/source/pilot", json={"groups": groups}, headers=headers
            ).json()["results"]
        )
        == 2
    )
    assert len(app.state.db.rows("SELECT * FROM messages")) == 2
    loaded = Settings(data_dir=tmp_path).prepare()
    assert loaded.source_account == loaded.self_id == "work-account"
    assert (tmp_path / "source-binding.json").stat().st_mode & 0o777 == 0o600


def test_pilot_rejects_unbounded_selection_and_pause_stops_egress(tmp_path):
    app, client, headers = setup(tmp_path)
    client.post(
        "/api/source/bind", json={"account_id": "work-account"}, headers=headers
    )
    groups = [{"source_id": f"{i}@chatroom", "title": f"群{i}"} for i in range(3)]
    assert (
        client.post(
            "/api/source/pilot", json={"groups": groups}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/source/pilot",
            json={"groups": [{"source_id": ["invalid"]}]},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/source/pilot",
            json={"groups": [groups[0], groups[1] | {"project_id": "missing"}]},
            headers=headers,
        ).status_code
        == 422
    )
    assert not app.state.db.rows("SELECT * FROM conversations")
    client.post("/api/source/pilot", json={"groups": groups[:1]}, headers=headers)
    cid = app.state.db.rows("SELECT id FROM conversations")[0]["id"]
    assert (
        client.post(
            f"/api/conversations/{cid}/pause", json={}, headers=headers
        ).status_code
        == 200
    )
    row = app.state.db.rows("SELECT * FROM conversations")[0]
    assert row["allowlisted"] == row["egress"] == 0


def test_source_connection_errors_are_actionable_without_leaking_token(tmp_path):
    def factory(db):
        def fail(request):
            raise httpx.ConnectError("internal details", request=request)

        return Collector(
            db,
            httpx.Client(
                base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(fail)
            ),
        )

    app = create_app(Settings(data_dir=tmp_path), source_factory=factory)
    client = TestClient(app)
    result = client.post(
        "/api/source/probe",
        json={},
        headers={"Authorization": "Bearer " + app.state.db.token},
    )
    assert result.status_code == 422 and "wx-cli" in result.json()["error"]
    assert "internal details" not in result.text
