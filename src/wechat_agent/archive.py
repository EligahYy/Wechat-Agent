"""Resumable local-only history ingestion, independent of export files.

The adapter exposes sessions/messages; wx-cli is currently one implementation,
not the archival state machine. A completed scan does not prove remote history.
"""

import hashlib
import time

import httpx

from .collector import SourceError
from .db import dumps, now, uid
from .ingestion import ingest

SYSTEM = {
    "weixin",
    "filehelper",
    "fmessage",
    "newsapp",
    "mphelper",
    "brandsessionholder",
    "notification_messages",
    "medianote",
    "floatbottle",
    "qqmail",
    "qmessage",
    "tmessage",
    "weixinreminder",
    "masssendapp",
}


def discover(source):
    source.validate()
    found = {}
    offset = 0
    for _ in range(1000):
        response = source.client.get(
            "/api/v1/sessions", params={"limit": 100, "offset": offset, "order": "asc"}
        )
        response.raise_for_status()
        data = response.json()
        stats = data.get("stats", {})
        if stats.get("skipped") or stats.get("shard_warnings"):
            raise SourceError("discovery_partial")
        items = data["items"]
        more = data["paging"]["has_more"]
        if not isinstance(items, list) or not isinstance(more, bool):
            raise SourceError("invalid_sessions_paging")
        added = 0
        for item in items:
            row = item.get("session", item)
            sid = row.get("username")
            if not isinstance(sid, str) or not sid:
                raise SourceError("invalid_session_identity")
            if sid not in found:
                added += 1
            found[sid] = {
                "source_id": sid,
                "title": item.get("display_name") or sid,
                "kind": "group" if sid.endswith("@chatroom") else "private",
                "excluded": sid.startswith("gh_")
                or sid in SYSTEM
                or item.get("chat_type") in {"official_account", "folded"},
            }
        if not more:
            break
        if not items or not added:
            raise SourceError("sessions_pagination_stalled")
        offset += len(items)
    else:
        raise SourceError("sessions_pagination_limit")
    source.validate()
    if len(found) >= 20000:
        raise SourceError("discovery_source_limit_possible")
    return list(found.values())


def register(db, sessions, until, rescan=False):
    """One explicit local scope grant; never create merchants or grant egress."""
    with db.tx() as c:
        c.execute(
            "UPDATE conversations SET egress=0 WHERE source='wx_cli' AND account_id=?",
            (db.settings.source_account,),
        )
        for item in sessions:
            if item["excluded"]:
                continue
            row = c.execute(
                "SELECT id FROM conversations WHERE source='wx_cli' AND account_id=? AND source_id=?",
                (db.settings.source_account, item["source_id"]),
            ).fetchone()
            cid = row["id"] if row else uid()
            c.execute(
                "INSERT INTO conversations(id,source,account_id,source_id,title,kind,allowlisted,egress) VALUES(?,'wx_cli',?,?,?,?,1,0) ON CONFLICT(source,account_id,source_id) DO UPDATE SET title=excluded.title,allowlisted=1,egress=0",
                (
                    cid,
                    db.settings.source_account,
                    item["source_id"],
                    item["title"],
                    item["kind"],
                ),
            )
            c.execute(
                "INSERT OR IGNORE INTO archive_progress(conversation_id,until,status,updated_at) VALUES(?,?,'pending',?)",
                (cid, until, now()),
            )
            if rescan:
                c.execute(
                    "UPDATE archive_progress SET until=?,page_offset=0,status='pending',error=NULL,last_page_hash='',updated_at=? WHERE conversation_id=?",
                    (until, now(), cid),
                )
                c.execute("DELETE FROM archive_issues WHERE conversation_id=?", (cid,))
            c.execute(
                "UPDATE suggestions SET status='stale' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE json_extract(payload,'$.conversation_id')=?)",
                (cid,),
            )
        db.event(
            c,
            db.settings.source_account,
            "archive_scope_granted",
            {
                "conversations": sum(not s["excluded"] for s in sessions),
                "egress": False,
                "rescan": rescan,
            },
        )


def import_history(db, source, emit=lambda event: None, delay=0.1):
    source.validate()
    chats = db.rows(
        "SELECT c.* FROM conversations c JOIN archive_progress p ON p.conversation_id=c.id WHERE c.source='wx_cli' AND c.account_id=? AND c.allowlisted=1 AND p.status NOT IN ('scanned','scanned_with_gaps') ORDER BY c.id",
        (db.settings.source_account,),
    )
    for chat in chats:
        try:
            for _ in range(100000):
                source.validate()
                progress = db.rows(
                    "SELECT * FROM archive_progress WHERE conversation_id=?",
                    (chat["id"],),
                )[0]
                response = source.client.get(
                    "/api/v1/messages",
                    params={
                        "contact": chat["source_id"],
                        "since": 0,
                        "until": progress["until"],
                        "order": "asc",
                        "limit": 200,
                        "offset": progress["page_offset"],
                    },
                )
                response.raise_for_status()
                data = response.json()
                stats = data.get("stats", {})
                if stats.get("skipped") or stats.get("shard_warnings"):
                    raise SourceError("history_partial_shards")
                items = data["items"]
                more = data["paging"]["has_more"]
                if (
                    not isinstance(items, list)
                    or len(items) > 200
                    or not isinstance(more, bool)
                ):
                    raise SourceError("invalid_history_page")
                page_hash = hashlib.sha256(dumps(items).encode()).hexdigest()
                if more and (not items or page_hash == progress["last_page_hash"]):
                    raise SourceError("history_pagination_stalled")
                records = []
                issues = []
                for item in items:
                    try:
                        records.append(
                            source.normalize_message(chat, item, 0, progress["until"])
                        )
                    except (SourceError, KeyError, TypeError, ValueError) as exc:
                        code = (
                            str(exc)
                            if isinstance(exc, SourceError)
                            else type(exc).__name__
                        )
                        if code in {"conversation_mismatch", "out_of_window"}:
                            raise SourceError(code)
                        issues.append(
                            (hashlib.sha256(dumps(item).encode()).hexdigest(), code)
                        )
                with db.tx() as c:
                    current = c.execute(
                        "SELECT allowlisted,egress FROM conversations WHERE id=?",
                        (chat["id"],),
                    ).fetchone()
                    if not current or not current["allowlisted"]:
                        raise SourceError("archive_conversation_paused")
                    if current["egress"]:
                        raise SourceError("archive_egress_policy_changed")
                    result = ingest(db, records, analyze=False, connection=c)
                    for row_hash, code in issues:
                        c.execute(
                            "INSERT OR IGNORE INTO archive_issues VALUES(?,?,?)",
                            (chat["id"], row_hash, code),
                        )
                    gaps = c.execute(
                        "SELECT COUNT(*) FROM archive_issues WHERE conversation_id=?",
                        (chat["id"],),
                    ).fetchone()[0]
                    status = (
                        "pending"
                        if more
                        else ("scanned_with_gaps" if gaps else "scanned")
                    )
                    c.execute(
                        "UPDATE archive_progress SET page_offset=?,status=?,error=NULL,updated_at=?,last_page_hash=? WHERE conversation_id=?",
                        (
                            progress["page_offset"] + len(items),
                            status,
                            now(),
                            page_hash,
                            chat["id"],
                        ),
                    )
                emit(
                    {
                        "conversation_id": chat["id"],
                        "status": status,
                        "processed": progress["page_offset"] + len(items),
                        "issues": gaps,
                        **result,
                    }
                )
                if not more:
                    break
                if delay:
                    time.sleep(delay)
            else:
                raise SourceError("history_page_limit")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            error = str(exc) if isinstance(exc, SourceError) else type(exc).__name__
            with db.tx() as c:
                c.execute(
                    "UPDATE archive_progress SET status='failed',error=?,updated_at=? WHERE conversation_id=?",
                    (error, now(), chat["id"]),
                )
            emit({"conversation_id": chat["id"], "status": "failed", "error": error})
    return status_report(db)


def status_report(db):
    return {
        "scope": "local_visible_sessions_only",
        "progress": db.rows(
            "SELECT p.status,COUNT(*) conversations,SUM(p.page_offset) source_rows FROM archive_progress p JOIN conversations c ON c.id=p.conversation_id WHERE c.account_id=? GROUP BY p.status",
            (db.settings.source_account,),
        ),
        "issues": db.rows(
            "SELECT i.error,COUNT(*) count FROM archive_issues i JOIN conversations c ON c.id=i.conversation_id WHERE c.account_id=? GROUP BY i.error",
            (db.settings.source_account,),
        ),
        "messages": db.rows(
            "SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.source IN ('wx_cli','manual') AND c.account_id=?",
            (db.settings.source_account,),
        )[0]["n"],
        "note": "扫描结果仅涵盖源端可见会话；隐藏/删除/未同步历史不保证覆盖。",
    }
