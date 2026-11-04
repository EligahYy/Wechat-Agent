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
