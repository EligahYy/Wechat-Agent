import httpx

from wechat_agent.collector import Collector
from wechat_agent.services import allow_conversation


def setup_source(db):
    db.settings.source_account = "real-account"
    db.settings.self_id = "real-account"
    cid = allow_conversation(db, "wx_cli", "real-account", "id@chatroom", "群", "group")
    return db.rows("SELECT * FROM conversations WHERE id=?", (cid,))[0]


def message(i):
    return {
        "server_id": i,
        "msg_type": 1,
        "talker": "id@chatroom",
        "sender": "merchant",
        "create_time": 100,
        "content": {"Text": "同秒真实消息"},
        "snippet": "摘要",
    }


def test_full_paging_and_replay(db):
    chat = setup_source(db)

    def handler(req):
        if req.url.path.endswith("/health"):
            return httpx.Response(
                200,
                json={
                    "ready": True,
                    "current_account": {"wxid": "real-account"},
                    "cli_version": "test",
                },
            )
        offset = int(req.url.params["offset"])
        return httpx.Response(
            200,
            json={
                "items": [message(offset + 1)],
                "paging": {"has_more": offset == 0},
                "stats": {"skipped": 0, "shard_warnings": []},
            },
        )

    source = Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(handler)
        ),
    )
    assert source.sync_window(chat, 90, 110)["inserted"] == 2
    assert source.sync_window(chat, 90, 110)["duplicates"] == 2
    assert len(db.rows("SELECT * FROM messages")) == 2


def test_snippet_not_promoted_and_gap_preserved(db):
    chat = setup_source(db)
    item = message(1)
    item.pop("content")
    client = httpx.Client(
        base_url="http://127.0.0.1:9100",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"ready": True, "current_account": {"wxid": "real-account"}}
                if r.url.path.endswith("/health")
                else {"items": [item], "paging": {"has_more": False}, "stats": {}},
            )
        ),
    )
    assert "error" in Collector(db, client).sync_window(chat, 90, 110)
    assert not db.rows("SELECT * FROM messages")
    assert db.rows("SELECT * FROM sync_windows")[0]["status"] == "gap"


def test_mismatched_account_never_requests(db):
    chat = setup_source(db)
    db.settings.source_account = "different-account"
    import pytest

    with pytest.raises(ValueError):
        Collector(db).sync_window(chat, 90, 110)


def test_source_switch_during_restart_is_rejected(db):
    chat = setup_source(db)
    client = httpx.Client(
        base_url="http://127.0.0.1:9100",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"ready": True, "current_account": {"wxid": "another-account"}},
            )
        ),
    )
    result = Collector(db, client).sync_window(chat, 90, 110)
    assert result["error"] == "source_account_mismatch_or_unconfigured"
    assert not db.rows("SELECT * FROM messages")


def test_missing_sender_not_guessed_as_contact_or_self(db):
    chat = setup_source(db)
    c = Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100",
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        ),
    )
    for sender in ("", None):
        record = c.normalize_message(chat, message(1) | {"sender": sender}, 90, 110)
        assert record["sender_id"] == "unknown" and record["direction"] == "unknown"
        assert record["source_locator"]["sender_resolution"] == "missing"
        assert record["text"] == "同秒真实消息"
