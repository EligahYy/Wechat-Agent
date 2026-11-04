import httpx
import pytest

from wechat_agent.archive import discover, import_history, register
from wechat_agent.collector import Collector, SourceError


def make_source(db, handler):
    db.settings.source_account = db.settings.self_id = "account"

    def dispatch(req):
        if req.url.path.endswith("/health"):
            return httpx.Response(
                200, json={"ready": True, "current_account": {"wxid": "account"}}
            )
        return handler(req)

    return Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(dispatch)
        ),
    )


def item(i, chat="person"):
    return {
        "server_id": i,
        "talker": chat,
        "sender": "person",
        "create_time": 100,
        "msg_type": 1,
        "content": {"Text": f"历史 {i}"},
    }


def test_discover_all_private_and_groups_and_exclude_system(db):
    def handler(req):
        offset = int(req.url.params["offset"])
        return httpx.Response(
            200,
            json={
                "items": [
                    {"username": sid, "display_name": sid}
                    for sid in (
                        ["person", "gh_official"]
                        if offset == 0
                        else ["room@chatroom", "filehelper"]
                    )
                ],
                "paging": {"has_more": offset == 0},
                "stats": {},
            },
        )

    sessions = discover(make_source(db, handler))
    assert len(sessions) == 4 and sum(s["excluded"] for s in sessions) == 2
    register(db, sessions, 500)
    chats = db.rows("SELECT * FROM conversations")
    assert {c["kind"] for c in chats} == {"private", "group"}
    assert all(c["egress"] == 0 and c["merchant_id"] is None for c in chats)


def test_resumable_pages_no_ai_jobs_and_idempotent_rescan(db):
    fail = {"enabled": True}
    offsets = []

    def handler(req):
        offset = int(req.url.params["offset"])
        offsets.append(offset)
        if offset == 2 and fail["enabled"]:
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={
                "items": [item(1), item(2)] if offset == 0 else [item(3)],
                "paging": {"has_more": offset == 0},
                "stats": {},
            },
        )

    source = make_source(db, handler)
    sessions = [
        {"source_id": "person", "title": "个人", "kind": "private", "excluded": False}
    ]
    register(db, sessions, 500)
    report = import_history(db, source, delay=0)
    assert report["messages"] == 2 and report["progress"][0]["status"] == "failed"
    assert db.rows("SELECT * FROM archive_progress")[0]["page_offset"] == 2
    assert not db.rows("SELECT * FROM jobs") and not db.rows("SELECT * FROM merchants")
    fail["enabled"] = False
    offsets.clear()
    assert import_history(db, source, delay=0)["messages"] == 3 and offsets == [2]
    assert db.rows("SELECT * FROM archive_progress")[0]["status"] == "scanned"
    offsets.clear()
    import_history(db, source, delay=0)
    assert not offsets
    register(db, sessions, 600, rescan=True)
    assert import_history(db, source, delay=0)["messages"] == 3


def test_bad_record_is_reported_as_gap_not_full_success(db):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "items": [item(1), item(0)],
                "paging": {"has_more": False},
                "stats": {},
            },
        )

    source = make_source(db, handler)
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    report = import_history(db, source, delay=0)
    assert (
        report["messages"] == 1
        and report["progress"][0]["status"] == "scanned_with_gaps"
    )
    assert report["issues"][0]["error"] == "stable_server_id_unavailable"


def test_page_write_and_offset_rollback_together(db, monkeypatch):
    def handler(req):
        return httpx.Response(
            200, json={"items": [item(1)], "paging": {"has_more": False}, "stats": {}}
        )

    source = make_source(db, handler)
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    import wechat_agent.archive as module

    original = module.ingest

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("simulated interruption before checkpoint")

    monkeypatch.setattr(module, "ingest", failing)
    import_history(db, source, delay=0)
    assert not db.rows("SELECT * FROM messages")
    assert db.rows("SELECT * FROM archive_progress")[0]["page_offset"] == 0


def test_discovery_repeated_page_rejected(db):
    source = make_source(
        db,
        lambda req: httpx.Response(
            200, json={"items": [{"username": "person"}], "paging": {"has_more": True}}
        ),
    )
    with pytest.raises(SourceError, match="pagination_stalled"):
        discover(source)


def test_incremental_starts_at_history_cutoff_not_now(db, monkeypatch):
    source = make_source(db, lambda req: httpx.Response(200))
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        10000,
    )
    windows = []

    def scan(chat, since, until):
        windows.append((since, until))
        return {"inserted": 0}

    monkeypatch.setattr(source, "sync_window", scan)
    source.tick()
    assert windows[0][0] == 9100


def test_cli_partial_scan_has_nonzero_exit(db, monkeypatch):
    from wechat_agent import cli

    def handler(req):
        if req.url.path.endswith("/sessions"):
            return httpx.Response(
                200,
                json={"items": [{"username": "person"}], "paging": {"has_more": False}},
            )
        return httpx.Response(
            200, json={"items": [item(0)], "paging": {"has_more": False}, "stats": {}}
        )

    monkeypatch.setattr(cli, "Collector", lambda store: make_source(store, handler))
    monkeypatch.setattr(
        "sys.argv",
        [
            "wechat-agent",
            "--data-dir",
            str(db.settings.data_dir),
            "archive",
            "init-all",
            "--account",
            "account",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_unknown_sender_preserves_body_reports_warning_and_can_repair(db):
    from wechat_agent.archive import repair_metadata

    def handler(req):
        return httpx.Response(
            200,
            json={
                "items": [item(1) | {"sender": ""}],
                "paging": {"has_more": False},
                "stats": {},
            },
        )

    source = make_source(db, handler)
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    cid = db.rows("SELECT id FROM conversations")[0]["id"]
    with db.tx() as c:
        c.execute(
            "INSERT INTO archive_issues VALUES(?,'old-hash','sender_unavailable')",
            (cid,),
        )
        c.execute(
            "UPDATE archive_progress SET status='scanned_with_gaps',page_offset=1 WHERE conversation_id=?",
            (cid,),
        )
    assert repair_metadata(db) == 1
    report = import_history(db, source, delay=0)
    assert report["messages"] == 1 and not report["issues"]
    row = db.rows("SELECT * FROM messages")[0]
    assert (
        row["text"] == "历史 1"
        and row["sender_id"] == "unknown"
        and row["direction"] == "unknown"
    )
    assert report["metadata_warnings"]["messages"] == 1
    assert report["progress"][0]["status"] == "scanned"


def test_failure_report_has_safe_details_and_http_code(db):
    from wechat_agent.archive import status_report

    source = make_source(
        db, lambda req: httpx.Response(404, json={"secret": "should not leak"})
    )
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    import_history(db, source, delay=0)
    report = status_report(db, details=True)
    assert report["failure_reasons"] == [{"error": "HTTP_404", "conversations": 1}]
    assert report["failed_conversations"][0]["page_offset"] == 0
    assert "should not leak" not in str(report)
    assert status_report(db)["failed_conversations"] == []


def test_validation_error_is_field_specific_and_does_not_block_page(db):

    secret_text = "PRIVATE-CONTENT-MUST-NOT-ENTER-REPORT"
    invalid = item(2) | {"sender": "s" * 201, "content": {"Text": secret_text}}
    source = make_source(
        db,
        lambda req: httpx.Response(
            200,
            json={
                "items": [item(1), invalid, item(3)],
                "paging": {"has_more": False},
                "stats": {},
            },
        ),
    )
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    events = []
    report = import_history(db, source, emit=events.append, delay=0)
    assert report["messages"] == 2 and report["quarantined_rows"] == 1
    assert report["progress"][0]["status"] == "scanned_with_gaps"
    assert report["issues"][0]["error"] == "validation:sender_id:string_too_long"
    assert secret_text not in str(report) and secret_text not in str(events)
    assert (
        secret_text in db.rows("SELECT payload FROM archive_quarantine")[0]["payload"]
    )
    assert db.rows("SELECT * FROM archive_progress")[0]["page_offset"] == 3
    assert not db.rows("SELECT * FROM jobs")


def test_http400_classification_never_returns_arbitrary_body(db):

    source = make_source(
        db,
        lambda req: httpx.Response(
            400, json={"error": "ambiguous contact PRIVATE_NAME"}
        ),
    )
    register(
        db,
        [
            {
                "source_id": "person",
                "title": "个人",
                "kind": "private",
                "excluded": False,
            }
        ],
        500,
    )
    report = import_history(db, source, delay=0)
    assert report["failure_reasons"] == [
        {"error": "HTTP_400:ambiguous_contact", "conversations": 1}
    ]
    assert "PRIVATE_NAME" not in str(report)
