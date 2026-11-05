import csv
import io
import json

from fastapi.testclient import TestClient

from wechat_agent.file_import import import_file
from wechat_agent.ingestion import ingest
from wechat_agent.web import create_app


def exported(sid=1, kind="direct", chat="person"):
    return {
        "source": "wx_cli",
        "account_id": "account",
        "conversation_id": chat,
        "conversation_type": "group" if kind == "group" else "private",
        "source_id": str(sid),
        "sender_id": "person",
        "direction": "incoming",
        "event_time": "2026-11-04T09:00:00+08:00",
        "message_type": "text",
        "text": "请核实附加费",
    }


def test_standard_csv_json_share_native_identity_and_no_ai(db):
    db.settings.source_account = db.settings.self_id = "account"
    buffer = io.StringIO()
    row = exported()
    writer = csv.DictWriter(buffer, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    preview = import_file(db, buffer.getvalue(), "all_messages.csv", "account")
    assert (
        preview["valid"] == 1
        and not preview["written"]
        and not db.rows("SELECT * FROM messages")
    )
    assert (
        import_file(db, buffer.getvalue(), "all_messages.csv", "account", True)[
            "inserted"
        ]
        == 1
    )
    assert (
        import_file(db, json.dumps([row]), "all_messages.json", "account", True)[
            "duplicates"
        ]
        == 1
    )
    assert not db.rows("SELECT * FROM jobs")
    assert db.rows("SELECT * FROM conversations")[0]["egress"] == 0
    native = {
        "source": "wx_cli",
        "account_id": "account",
        "conversation_id": "person",
        "conversation_type": "private",
        "source_id": "1",
        "sender_id": "person",
        "direction": "incoming",
        "event_time": "2026-11-04T09:00:00+08:00",
        "message_type": "text",
        "text": "请核实附加费",
    }
    assert ingest(db, [native])["duplicates"] == 1
    assert len(db.rows("SELECT * FROM messages")) == 1


def test_invalid_file_is_previewed_and_no_partial_write(db):
    rows = [exported(), exported() | {"conversation_id": ""}]
    assert (
        import_file(db, json.dumps(rows), "all_messages.json", "account")["rejected"]
        == 1
    )
    import pytest

    with pytest.raises(ValueError):
        import_file(db, json.dumps(rows), "all_messages.json", "account", True)
    assert not db.rows("SELECT * FROM conversations") and not db.rows(
        "SELECT * FROM messages"
    )


def test_personal_and_group_timeline_unified_but_same_name_distinct(db):
    db.settings.source_account = db.settings.self_id = "account"
    rows = [
        exported(1),
        exported(2, "group", "room@chatroom"),
        exported(3, "direct", "another") | {"sender_id": "another"},
    ]
    import_file(db, json.dumps(rows), "all_messages.json", "account", True)
    app = create_app(db.settings)
    c = TestClient(app)
    headers = {"Authorization": "Bearer " + db.token}
    customers = c.get("/api/customers", headers=headers).json()
    assert {r["identity"] for r in customers["items"]} == {"person", "another"}
    timeline = c.get("/api/customers/person/timeline", headers=headers).json()
    assert len(timeline) == 2 and {m["conversation_kind"] for m in timeline} == {
        "private",
        "group",
    }
    archive = c.get("/api/archive/conversations", headers=headers).json()
    assert archive["total"] == 3


def test_file_http_preview_and_import_stay_local(db):
    db.settings.source_account = "account"
    app = create_app(db.settings)
    c = TestClient(app)
    h = {"Authorization": "Bearer " + db.token}
    body = {"filename": "all_messages.json", "text": json.dumps([exported()])}
    assert c.post("/api/imports/file", json=body, headers=h).json()["valid"] == 1
    assert not db.rows("SELECT * FROM messages")
    assert (
        c.post("/api/imports/file", json=body | {"write": True}, headers=h).json()[
            "inserted"
        ]
        == 1
    )
    assert not db.rows("SELECT * FROM usage")


def test_offline_import_can_select_work_account_and_manual_source_visible(db, record):
    result = import_file(
        db, json.dumps([record | {"source": "manual"}]), "manual.json", "account", True
    )
    assert result["inserted"] == 1 and db.settings.source_account == "account"
    app = create_app(db.settings)
    web = TestClient(app)
    h = {"Authorization": "Bearer " + db.token}
    assert web.get("/api/archive/conversations", headers=h).json()["total"] == 1
