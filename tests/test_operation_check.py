"""The Mac verifier creates only a bounded source job and prints no personal data."""

from contextlib import closing
import json

import pytest


def test_verifier_uses_real_api_worker_and_reports_only_technical_state(tmp_path):
    from fastapi.testclient import TestClient
    from tests.factories import seed_case
    from tests.fakes.source import FakeSource
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.operations.check import check_operation
    from wechat_agent.services import Services
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        migrate(conn)
        seed_case(conn)
    with TestClient(create_app(Settings(data_dir=tmp_path), Services(source=FakeSource()))) as client:
        report = check_operation(client, "acct-1")
        assert report["state"] == report["source_state"] == "succeeded"
        assert report["counts"]["unchanged"] == 4
        assert report["history_complete"] is False
        operation = client.get(f"/api/operations/{report['operation_id']}", params={"account_id":"acct-1"}).json()
        assert operation["action"] == "sync"
        assert operation["options"]["sample"] is True
        assert operation["options"]["from_start"] is True
        for private in ("acct-1", "merchant-a", "group-1", "商家甲", str(tmp_path)):
            assert private not in json.dumps(report, ensure_ascii=False)


def test_verifier_output_cannot_overwrite_archive(tmp_path, monkeypatch):
    from wechat_agent.operations.check import main
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path))
    path = tmp_path / "archive.sqlite3"
    path.write_bytes(b"existing database")
    with pytest.raises(SystemExit) as error:
        main(["--account", "acct-1", "--output", str(path)])
    assert error.value.code == 2
    assert path.read_bytes() == b"existing database"


def test_latest_diagnostic_reads_existing_failure_without_starting_a_job(client):
    from tests.factories import seed_case
    from wechat_agent.operations.check import check_operation
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)
    created = client.post("/api/operations", json={
        "action": "sync", "scope": {"account_id": "acct-1"}, "idempotency_key": "existing",
    }).json()
    with closing(open_db(client.app.state.database_path)) as conn, conn:
        conn.execute("UPDATE operations SET state='failed',error_code='source_incomplete' WHERE id=?", (created["id"],))
        conn.execute("UPDATE operation_items SET state='failed',gaps_json=? WHERE operation_id=?",
                     (json.dumps(["message_sender_invalid"]), created["id"]))
    report = check_operation(client, "acct-1", latest=True)
    assert report["operation_id"] == created["id"]
    assert report["source_gaps"] == ["message_sender_invalid"]
    assert report["contact_quality"]["quarantined"] == 0
    assert client.get("/api/operations", params={"account_id": "acct-1"}).json()["total"] == 1
    assert "acct-1" not in json.dumps(report)
