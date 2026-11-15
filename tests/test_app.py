"""The API reports its own database health without claiming source connectivity."""

from contextlib import closing
import socket

import pytest


def test_factory_has_no_filesystem_or_network_side_effects(tmp_path, monkeypatch):
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    def forbidden(*args, **kwargs):
        raise AssertionError("Health must not contact WeChat or models")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    root = tmp_path / "new-data"
    app = create_app(Settings(data_dir=root))
    assert not root.exists()
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "schema_version": 14}
    assert (root / "archive.sqlite3").is_file()


def test_health_reads_real_schema_and_reports_mismatch(client):
    assert client.get("/api/health").json() == {"status": "ok", "schema_version": 14}
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn, conn:
        conn.execute("UPDATE schema_version SET version=999")
    assert client.get("/api/health").status_code == 503
    assert client.get("/api/health").json()["code"] == "database_schema_mismatch"


def test_health_does_not_recreate_a_missing_database(client):
    path = client.app.state.database_path
    path.unlink()
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert not path.exists()
    assert str(path) not in response.text


def test_app_instances_have_separate_settings_and_service_state(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.services import Services
    services = Services(source=None)
    first = create_app(Settings(data_dir=tmp_path / "first"), services=services)
    second = create_app(Settings(data_dir=tmp_path / "second"))
    assert first.state.services is services
    assert second.state.services is not services
    with TestClient(first) as one, TestClient(second) as two:
        assert one.get("/api/health").status_code == two.get("/api/health").status_code == 200
        assert one.app.state.database_path != two.app.state.database_path


def test_newer_schema_blocks_startup(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn, conn:
        migrate(conn)
        conn.execute("UPDATE schema_version SET version=999")
    with pytest.raises(RuntimeError, match="database_schema_newer_than_app"):
        with TestClient(create_app(Settings(data_dir=tmp_path))):
            raise AssertionError("Newer schema must not start")
