import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import secret
from ..db import dumps
from ..identity import location
from .quality import display_text
from .store import allowed_chats, legacy_paused, read, source_chats


def candidates(db, q="", page=1):
    if len(q) > 100 or page < 1 or page > 10000:
        raise ValueError("workspace_invalid_query")
    account = db.settings.source_account
    ids = [v["id"] for v in source_chats(db)]
    # A private peer is known even if only our outgoing messages were archived.
    # Group membership comes from a real sender, never from a group ID/name.
    rows = db.rows(
        """WITH sources AS (
          SELECT CASE WHEN v.kind='private' THEN v.source_id ELSE m.sender_id END source_id,
                 v.egress, CASE WHEN v.kind='private' THEN NULLIF(v.title,v.source_id) END title,
                 m.type, m.completeness
          FROM messages m JOIN conversations v ON v.id=m.conversation_id
          WHERE v.id IN (SELECT value FROM json_each(?))
            AND (v.kind='private' OR (v.kind='group' AND m.direction<>'outgoing'))
        )
        SELECT s.source_id,
          COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),MAX(NULLIF(s.title,'')),'姓名待同步') name,
          MAX(s.egress) authorized,
          MAX(s.egress=1 AND s.type='text' AND s.completeness='full') has_text
        FROM sources s
        LEFT JOIN identity_metadata i ON i.account_id=? AND i.source_id=s.source_id
        WHERE s.source_id NOT IN ('unknown','',?,?) AND s.source_id NOT LIKE '%@chatroom'
          AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=? AND e.source_id=s.source_id)
        GROUP BY s.source_id ORDER BY name,s.source_id""",
        (
            dumps(ids),
            account,
            account,
            db.settings.self_id,
            account,
        ),
    )
    policy = db.rows("SELECT enabled FROM crm_policies WHERE account_id=?", (account,))
    enabled = bool(policy and policy[0]["enabled"])
    key = bool(secret("DEEPSEEK_API_KEY"))
    messages = db.rows(
        "SELECT COUNT(*) n FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=?",
        (account,),
    )[0]["n"]
    for row in rows:
        row["blocked_reason"] = (
            "analysis_disabled"
            if not enabled
            else "key_missing"
            if not key
            else "source_unauthorized"
            if not row["authorized"]
            else "no_text"
            if not row["has_text"]
            else None
        )
    reason = (
        "account_unbound"
        if not account
        else "no_archive"
        if not messages
        else "scope_excluded"
        if not ids
        else "no_identity"
        if not rows
        else None
    )
    diagnostics = {
        "archived_messages": messages,
        "scope_conversations": len(ids),
        "contacts": len(rows),
        "analysis_enabled": enabled,
        "key_configured": key,
        "empty_reason": reason,
    }
    rows = [
        r
        for r in rows
        if q.casefold() in r["name"].casefold()
        or q.casefold() in r["source_id"].casefold()
    ]
    pages = max(1, (len(rows) + 49) // 50)
    page = min(page, pages)
    return {
        "items": rows[(page - 1) * 50 : page * 50],
        "total": len(rows),
        "page": page,
        "has_more": len(rows) > page * 50,
        "diagnostics": diagnostics,
    }


def details(db, source_id):
    doc = read(db, source_id)
    if not doc:
        raise ValueError("workspace_not_found")
    if not doc["body"].get("pause_override"):
        doc["body"]["paused"] = legacy_paused(db, source_id)
    locator = location(db, source_id)
    allowed = {v["id"] for v in allowed_chats(db)}
    locator["conversations"] = [
        v for v in locator["conversations"] if v["id"] in allowed
    ]
    doc.update(
        source_id=source_id,
        name=locator["remark"] or locator["nickname"] or "姓名待同步",
        location=locator,
    )
    row = db.rows("SELECT read_set FROM workspace_documents WHERE id=?", (doc["id"],))[
        0
    ]
    ids = [r["id"] for r in json.loads(row["read_set"])]
    doc["evidence"] = db.rows(
        "SELECT m.id,m.text,m.event_time,v.title conversation FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id IN (SELECT value FROM json_each(?)) ORDER BY m.event_time,m.id",
        (dumps(ids),),
    )
    from .context import snapshot

    doc["needs_update"] = doc["body"].get("source_revision") != snapshot(
        db, source_id, False
    )
    for section in ("notes", "batches", "actions", "decisions"):
        for item in doc["body"][section].values():
            item["text"] = display_text(item["text"])
    doc["can_followup"] = bool(
        doc["body"]["relationship"] == "merchant"
        and not doc["body"].get("quality_issues")
        and not doc["body"]["paused"]
        and locator["quality"] == "named"
        and not doc["needs_update"]
    )
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    doc["today_action_ids"] = [
        k
        for k, a in doc["body"]["actions"].items()
        if doc["can_followup"]
        and (doc["body"]["coverage"]["complete_context"] or a.get("confirmed"))
        and a["state"] == "open"
        and (not a["due_date"] or a["due_date"] <= today)
    ]
    return doc


def listing(db):
    items = []
    stale = 0
    for row in db.rows(
        "SELECT source_id FROM workspace_documents WHERE account_id=? ORDER BY updated_at DESC",
        (db.settings.source_account,),
    ):
        try:
            d = details(db, row["source_id"])
        except ValueError as exc:
            stale += str(exc) == "workspace_stale_evidence"
            continue
        if d["body"]["relationship"] == "non_target":
            continue
        items.append(d)
    return {"items": items, "stale_documents": stale}
