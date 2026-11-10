import base64
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from wechat_agent.collector import Collector
from wechat_agent.db import DB, SCHEMA
from wechat_agent.ingestion import ingest
from wechat_agent.web import create_app

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lWQAAAAASUVORK5CYII="
)


def image_record(record):
    return record | {
        "source": "wx_cli",
        "message_type": "3",
        "text": "[图片]",
        "completeness": "metadata",
        "source_locator": {"image_md5": "a" * 32},
    }


def setup(db, chat, record, status=200, body=PNG):
    # The fixture chat starts as a synthetic source. Explicitly rebind to a real
    # adapter contract; no live data or upstream connection is used.
    with db.tx() as c:
        c.execute("UPDATE conversations SET source='wx_cli' WHERE id=?", (chat,))
    ingest(db, [image_record(record)])
    db.settings.source_account = db.settings.self_id = "account"
    requests = []

    def factory(store):
        def handler(req):
            requests.append(str(req.url.path))
            if req.url.path.endswith("/health"):
                return httpx.Response(
                    200, json={"ready": True, "current_account": {"wxid": "account"}}
                )
            assert (
                req.url.params["talker"] == "chat"
                and req.url.params["server_id"] == "1"
            )
            return httpx.Response(
                status, content=body, headers={"x-wechat-media-quality": "thumbnail"}
            )

        return Collector(
            store,
            httpx.Client(
                base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(handler)
            ),
        )

    app = create_app(db.settings, source_factory=factory)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + db.token}
    mid = db.rows("SELECT id FROM messages")[0]["id"]
    return client, headers, mid, requests


def test_image_local_fetch_cache_quality_and_no_model(db, chat, record):
    client, h, mid, requests = setup(db, chat, record)
    assert client.get(f"/api/messages/{mid}/image").status_code == 401
    r = client.get(f"/api/messages/{mid}/image", headers=h)
    assert (
        r.status_code == 200
        and r.content == PNG
        and r.headers["content-type"] == "image/png"
    )
    assert r.headers["x-wechat-media-quality"] == "thumbnail"
    count = len(requests)
    assert client.get(f"/api/messages/{mid}/image", headers=h).content == PNG
    assert len(requests) == count and "/chat/completions" not in requests
    meta = db.rows("SELECT * FROM attachments")[0]
    assert (
        db.settings.data_dir / "media" / (meta["sha256"] + ".bin")
    ).stat().st_mode & 0o777 == 0o600
    row = db.rows("SELECT * FROM messages")[0]
    assert json.loads(row["source_locator"])["image_md5"] == "a" * 32
    assert not db.rows("SELECT * FROM usage")


@pytest.mark.parametrize(
    "status,body", [(404, b""), (200, b"<html>not an image</html>")]
)
def test_missing_or_invalid_image_is_visible_error_not_cached(
    db, chat, record, status, body
):
    client, h, mid, _ = setup(db, chat, record, status, body)
    assert client.get(f"/api/messages/{mid}/image", headers=h).status_code == 422
    assert not db.rows("SELECT * FROM attachments")


def test_image_revision_invalidates_cache(db, chat, record):
    client, h, mid, _ = setup(db, chat, record)
    assert client.get(f"/api/messages/{mid}/image", headers=h).status_code == 200
    ingest(db, [image_record(record) | {"source_locator": {"image_md5": "b" * 32}}])
    assert not db.rows("SELECT * FROM attachments")


def test_v2_migration_preserves_database(tmp_path):
    from wechat_agent.config import Settings

    p = tmp_path / "agent.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(
        SCHEMA
        + "CREATE TABLE contact_roles(conversation_id TEXT,sender_id TEXT,role TEXT,display_name TEXT); INSERT INTO merchants VALUES('old','旧商家',0,'2026-01-01'); PRAGMA user_version=2;"
    )
    c.close()
    db = DB(Settings(data_dir=tmp_path))
    assert db.rows("SELECT * FROM merchants")[0]["name"] == "旧商家"
    assert db.rows("PRAGMA user_version")[0]["user_version"] == 15
    assert "source_locator" in {
        r["name"] for r in db.rows("PRAGMA table_info(messages)")
    }
