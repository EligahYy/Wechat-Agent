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
    rows = source_people(db)
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


def source_people(db):
    account = db.settings.source_account
    ids = [v["id"] for v in source_chats(db)]
    # A private peer is known even if only our outgoing messages were archived.
    # Group membership comes from a real sender, never from a group ID/name.
    return db.rows(
        """WITH sources AS (
          SELECT CASE WHEN v.kind='private' THEN v.source_id ELSE m.sender_id END source_id,
                 v.egress,m.event_time, CASE WHEN v.kind='private' THEN NULLIF(v.title,v.source_id) END title,
                 m.type, m.completeness
          FROM messages m JOIN conversations v ON v.id=m.conversation_id
          WHERE v.id IN (SELECT value FROM json_each(?))
            AND (v.kind='private' OR (v.kind='group' AND m.direction<>'outgoing'))
        )
        SELECT s.source_id,
          COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),MAX(NULLIF(s.title,'')),'姓名待同步') name,
          MAX(s.event_time) latest_event,
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
    ids = {
        r["id"]
        for section in ("notes", "batches", "actions", "decisions")
        for item in doc["body"][section].values()
        for r in item.get("evidence", [])
    }
    ids.update(
        r["id"]
        for item in doc["body"].get("unattributed", [])
        for r in item.get("evidence", [])
    )
    doc["evidence"] = db.rows(
        "SELECT m.id,m.text,m.event_time,v.title conversation FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id IN (SELECT value FROM json_each(?)) ORDER BY m.event_time,m.id",
        (dumps(list(ids)),),
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
    doc["task_groups"] = {"upcoming": [], "waiting": [], "done": []}
    for key, action in doc["body"]["actions"].items():
        if action["state"] == "done":
            doc["task_groups"]["done"].append(key)
        elif doc["can_followup"] and (
            doc["body"]["coverage"]["complete_context"] or action.get("confirmed")
        ):
            if action["state"] == "waiting":
                doc["task_groups"]["waiting"].append(key)
            elif (
                action["state"] == "open"
                and action.get("due_date")
                and action["due_date"] > today
            ):
                doc["task_groups"]["upcoming"].append(key)
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


def sources(db, source_id, page=1):
    from .context import related_chats
    from .store import eligible

    eligible(db, source_id)
    if page < 1 or page > 100000:
        raise ValueError("workspace_invalid_query")
    ids = [c["id"] for c in related_chats(db, source_id)]
    total = db.rows(
        "SELECT COUNT(*) n FROM messages WHERE conversation_id IN (SELECT value FROM json_each(?))",
        (dumps(list(ids)),),
    )[0]["n"]
    rows = db.rows(
        "SELECT m.id,m.text,m.event_time,m.type,m.completeness,m.sender_id,m.direction,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),m.sender_id) sender_name,v.title conversation FROM messages m JOIN conversations v ON v.id=m.conversation_id LEFT JOIN identity_metadata i ON i.account_id=v.account_id AND i.source_id=m.sender_id WHERE m.conversation_id IN (SELECT value FROM json_each(?)) ORDER BY m.event_time DESC,m.id DESC LIMIT 50 OFFSET ?",
        (dumps(ids), (page - 1) * 50),
    )
    return {"items": rows, "total": total, "page": page, "has_more": total > page * 50}


def packets(db, source_id, page=1):
    from .store import eligible, valid_refs

    eligible(db, source_id)
    if page < 1 or page > 100000:
        raise ValueError("workspace_invalid_query")
    # Packet history remains inspectable only while all its source refs remain
    # authorized and unmodified. It is not a second source of customer truth.
    rows = db.rows(
        "SELECT kind,body,read_set,created_at FROM workspace_packets WHERE account_id=? AND source_id=? ORDER BY created_at DESC LIMIT 10 OFFSET ?",
        (db.settings.source_account, source_id, (page - 1) * 10),
    )
    from .store import stable

    items = []
    for r in rows:
        refs = json.loads(r["read_set"])
        if not valid_refs(db, refs):
            continue
        mapping = {stable("evidence", ref["id"], ref["revision"]): ref for ref in refs}
        body = json.loads(r["body"])
        for fact in body["facts"]:
            fact["evidence"] = [mapping[k] for k in fact["evidence"] if k in mapping]
        ids = [ref["id"] for ref in refs]
        evidence = db.rows(
            "SELECT m.id,m.text,m.event_time,v.title conversation FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id IN (SELECT value FROM json_each(?)) ORDER BY m.event_time,m.id",
            (dumps(ids),),
        )
        items.append(
            {
                "kind": r["kind"],
                "body": body,
                "evidence": evidence,
                "created_at": r["created_at"],
            }
        )
    return {"items": items, "page": page, "has_more": len(rows) == 10}
