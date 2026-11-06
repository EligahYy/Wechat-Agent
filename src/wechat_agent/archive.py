"""Resumable local-only history ingestion, independent of export files.

The adapter exposes sessions/messages; wx-cli is currently one implementation,
not the archival state machine. A completed scan does not prove remote history.
"""

import hashlib
import time

import httpx
from pydantic import ValidationError

from .collector import SourceError
from .db import dumps, now, uid
from .ingestion import ingest
from .schemas import Message

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
                "title": item.get("display_name")
                or row.get("display_name")
                or row.get("name")
                or row.get("nick_name")
                or sid,
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


def register(db, sessions, until, rescan=False, preserve_paused=False):
    """Discover locally; inherit only an explicitly authorized account policy."""
    with db.tx() as c:
        policy = c.execute(
            "SELECT * FROM crm_policies WHERE account_id=?",
            (db.settings.source_account,),
        ).fetchone()
        grant = int(bool(policy and policy["enabled"] and policy["include_new"]))
        for item in sessions:
            if item["excluded"]:
                continue
            row = c.execute(
                "SELECT id,allowlisted FROM conversations WHERE source='wx_cli' AND account_id=? AND source_id=?",
                (db.settings.source_account, item["source_id"]),
            ).fetchone()
            if row and preserve_paused and not row["allowlisted"]:
                continue
            cid = row["id"] if row else uid()
            from .identity import clean_name

            meta = c.execute(
                "SELECT remark,nickname FROM identity_metadata WHERE account_id=? AND source_id=?",
                (db.settings.source_account, item["source_id"]),
            ).fetchone()
            title = (
                (meta["remark"] or meta["nickname"])
                if meta and (meta["remark"] or meta["nickname"])
                else clean_name(item["title"], item["source_id"])
            )
            c.execute(
                "INSERT INTO conversations(id,source,account_id,source_id,title,kind,allowlisted,egress,followup_source) VALUES(?,'wx_cli',?,?,?,?,1,?,1) ON CONFLICT(source,account_id,source_id) DO UPDATE SET title=excluded.title,allowlisted=1",
                (
                    cid,
                    db.settings.source_account,
                    item["source_id"],
                    title,
                    item["kind"],
                    grant,
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


def import_history(
    db, source, emit=lambda event: None, delay=0.1, max_pages=None, stop=None
):
    source.validate()
    chats = db.rows(
        "SELECT c.* FROM conversations c JOIN archive_progress p ON p.conversation_id=c.id WHERE c.source='wx_cli' AND c.account_id=? AND c.allowlisted=1 AND p.status NOT IN ('scanned','scanned_with_gaps') ORDER BY c.id",
        (db.settings.source_account,),
    )
    for chat in chats:
        try:
            for _ in range(max_pages or 100000):
                if stop and stop.is_set():
                    return status_report(db)
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
                quarantine = []
                for item in items:
                    try:
                        normalized = source.normalize_message(
                            chat, item, 0, progress["until"]
                        )
                        records.append(
                            Message.model_validate(normalized).model_dump(mode="json")
                        )
                    except ValidationError as exc:
                        # Field names and error types only: no input, message text,
                        # validation context or exception repr enters logs.
                        labels = []
                        for error in exc.errors(
                            include_input=False,
                            include_context=False,
                            include_url=False,
                        ):
                            field = error["loc"][0] if error["loc"] else "record"
                            if field not in Message.model_fields:
                                field = "record"
                            labels.append(str(field) + ":" + error["type"])
                        code = "validation:" + ",".join(sorted(set(labels)))
                        row_hash = hashlib.sha256(dumps(item).encode()).hexdigest()
                        issues.append((row_hash, code))
                        quarantine.append((row_hash, dumps(item), code))
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
                    result = ingest(db, records, analyze=False, connection=c)
                    for row_hash, code in issues:
                        c.execute(
                            "INSERT OR IGNORE INTO archive_issues VALUES(?,?,?)",
                            (chat["id"], row_hash, code),
                        )
                    for row_hash, payload, code in quarantine:
                        c.execute(
                            "INSERT OR REPLACE INTO archive_quarantine VALUES(?,?,?,?,?)",
                            (chat["id"], row_hash, payload, code, now()),
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
                if max_pages is None:
                    raise SourceError("history_page_limit")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            error = (
                str(exc)
                if isinstance(exc, SourceError)
                else http_error_code(exc)
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            with db.tx() as c:
                c.execute(
                    "UPDATE archive_progress SET status='failed',error=?,updated_at=? WHERE conversation_id=?",
                    (error, now(), chat["id"]),
                )
            emit({"conversation_id": chat["id"], "status": "failed", "error": error})
    return status_report(db)


def http_error_code(exc):
    code = f"HTTP_{exc.response.status_code}"
    if exc.response.status_code != 400:
        return code
    try:
        body = exc.response.json()
        message = body.get("error", "") if isinstance(body, dict) else ""
        if not isinstance(message, str):
            return code
        text = message.lower()
        if "ambig" in text:
            return code + ":ambiguous_contact"
        if "not found" in text or "no contact" in text or "no match" in text:
            return code + ":contact_not_found"
        if "missing" in text and "contact" in text:
            return code + ":missing_contact"
        if "since" in text or "until" in text:
            return code + ":time_range"
        if "offset" in text or "limit" in text:
            return code + ":paging_parameter"
    except ValueError:
        pass
    return code


def repair_metadata(db):
    """Revisit only chats with sender omissions, preserve good archived data."""
    with db.tx() as c:
        affected = c.execute(
            "SELECT DISTINCT c.id FROM conversations c JOIN archive_issues i ON i.conversation_id=c.id WHERE c.source='wx_cli' AND c.account_id=? AND i.error='sender_unavailable'",
            (db.settings.source_account,),
        ).fetchall()
        for row in affected:
            c.execute(
                "UPDATE archive_progress SET page_offset=0,status='pending',error=NULL,last_page_hash='',updated_at=? WHERE conversation_id=?",
                (now(), row["id"]),
            )
            c.execute(
                "DELETE FROM archive_issues WHERE conversation_id=?", (row["id"],)
            )
    return len(affected)


def status_report(db, details=False):
    return {
        "quarantined_rows": db.rows(
            "SELECT COUNT(*) n FROM archive_quarantine q JOIN conversations c ON c.id=q.conversation_id WHERE c.account_id=?",
            (db.settings.source_account,),
        )[0]["n"],
        "scope": "local_visible_sessions_only",
        "progress": db.rows(
            "SELECT p.status,COUNT(*) conversations,SUM(p.page_offset) source_rows FROM archive_progress p JOIN conversations c ON c.id=p.conversation_id WHERE c.account_id=? GROUP BY p.status",
            (db.settings.source_account,),
        ),
        "failure_reasons": db.rows(
            "SELECT p.error,COUNT(*) conversations FROM archive_progress p JOIN conversations c ON c.id=p.conversation_id WHERE c.account_id=? AND p.status='failed' GROUP BY p.error",
            (db.settings.source_account,),
        ),
        "failed_conversations": db.rows(
            "SELECT c.id conversation_id,c.kind,p.page_offset,p.until,p.error,p.updated_at FROM archive_progress p JOIN conversations c ON c.id=p.conversation_id WHERE c.account_id=? AND p.status='failed' ORDER BY c.id LIMIT 100",
            (db.settings.source_account,),
        )
        if details
        else [],
        "metadata_warnings": db.rows(
            "SELECT COUNT(*) messages FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.account_id=? AND json_extract(m.source_locator,'$.sender_resolution')='missing'",
            (db.settings.source_account,),
        )[0],
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
