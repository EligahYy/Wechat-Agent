from fastapi.testclient import TestClient

from wechat_agent.config import Settings
from wechat_agent.web import create_app


def test_local_auth_csrf_host_and_escaping(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    client = TestClient(app)
    db = app.state.db
    assert client.get("/api/state").status_code == 401
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/login",
            json={"token": db.token},
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.post("/login", json={"token": db.token}).status_code == 200
    assert client.post("/api/merchants", json={"name": "x"}).status_code == 403
    h = {"Authorization": "Bearer " + db.token}
    assert (
        client.post(
            "/api/merchants", json={"name": "<script>alert(1)</script>"}, headers=h
        ).status_code
        == 200
    )
    assert client.get("/").status_code == 200
    assert (
        "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    )


def test_business_result_requires_verified_milestone(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    c = TestClient(app)
    h = {"Authorization": "Bearer " + app.state.db.token}
    mid = c.post("/api/merchants", json={"name": "商家"}, headers=h).json()["id"]
    pid = c.post(
        "/api/projects",
        json={"merchant_id": mid, "name": "批次", "market": "美国"},
        headers=h,
    ).json()["id"]
    assert (
        c.post(
            f"/api/projects/{pid}/transition",
            json={"stage": "done", "version": 1},
            headers=h,
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/milestones",
            json={
                "project_id": pid,
                "kind": "stocking_result",
                "evidence_type": "chat_report",
                "verified": True,
                "note": "收到",
            },
            headers=h,
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/milestones",
            json={
                "project_id": pid,
                "kind": "stocking_result",
                "evidence_type": "manual_verification",
                "verified": True,
                "note": "人工核对平台结果",
            },
            headers=h,
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/projects/{pid}/transition",
            json={"stage": "done", "version": 1},
            headers=h,
        ).status_code
        == 200
    )


def test_expired_material_cannot_create_confirmed_quote(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    c = TestClient(app)
    h = {"Authorization": "Bearer " + app.state.db.token}
    mid = c.post("/api/merchants", json={"name": "商家"}, headers=h).json()["id"]
    pid = c.post(
        "/api/projects", json={"merchant_id": mid, "name": "批次"}, headers=h
    ).json()["id"]
    provider = c.post("/api/providers", json={"name": "服务商"}, headers=h).json()["id"]
    mat = c.post(
        "/api/materials",
        json={
            "name": "卡",
            "version": "v1",
            "market": "美国",
            "terms": "待确认",
            "scope": "external",
            "status": "approved",
            "valid_until": "2020-01-01T00:00:00+08:00",
        },
        headers=h,
    ).json()["id"]
    assert (
        c.post(
            "/api/quotes",
            json={
                "project_id": pid,
                "provider_id": provider,
                "material_id": mat,
                "terms": "100元",
                "confirmed": True,
            },
            headers=h,
        ).status_code
        == 422
    )


def test_malformed_and_missing_fields_are_422(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    c = TestClient(app)
    h = {"Authorization": "Bearer " + app.state.db.token}
    assert c.post("/api/merchants", json={}, headers=h).status_code == 422
    assert c.post("/api/merchants", json=[], headers=h).status_code == 422


def test_cross_site_entry_navigation_but_not_api_or_iframe(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    c = TestClient(app)
    navigation = {
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document",
        "sec-fetch-user": "?1",
    }
    entry = c.get("/", headers=navigation)
    assert entry.status_code == 200
    assert "本地登录" in entry.text
    assert "frame-ancestors 'none'" in entry.headers["content-security-policy"]
    assert entry.headers["cache-control"] == "no-store"
    assert c.get("/api/state", headers=navigation).status_code == 403
    assert (
        c.get("/", headers=navigation | {"sec-fetch-dest": "iframe"}).status_code == 403
    )
    assert (
        c.get("/", headers=navigation | {"sec-fetch-mode": "cors"}).status_code == 403
    )
    assert (
        c.post(
            "/login", json={"token": app.state.db.token}, headers=navigation
        ).status_code
        == 403
    )
    assert (
        c.get("/", headers=navigation | {"origin": "https://evil.example"}).status_code
        == 403
    )
    # Subsequent same-origin login and dashboard operations remain usable.
    assert (
        c.post(
            "/login",
            json={"token": app.state.db.token},
            headers={"sec-fetch-site": "same-origin"},
        ).status_code
        == 200
    )
    assert (
        c.get("/api/state", headers={"sec-fetch-site": "same-origin"}).status_code
        == 200
    )
    assert c.get("/api/state", headers=navigation).status_code == 403


def test_token_rotation_revokes_running_sessions(tmp_path):
    from wechat_agent.db import DB

    app = create_app(Settings(data_dir=tmp_path))
    c = TestClient(app)
    old = app.state.db.token
    assert c.post("/login", json={"token": old}).status_code == 200
    assert c.get("/api/state").status_code == 200
    other_process = DB(app.state.db.settings)
    other_process.rotate_token()
    assert other_process.token != old
    assert c.get("/api/state").status_code == 401
    assert (
        c.get("/api/state", headers={"Authorization": "Bearer " + old}).status_code
        == 401
    )
    assert c.post("/login", json={"token": old}).status_code == 401
    assert c.post("/login", json={"token": other_process.token}).status_code == 200
    assert c.get("/api/state").status_code == 200
    assert (tmp_path / "session-token").stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".session-*"))
