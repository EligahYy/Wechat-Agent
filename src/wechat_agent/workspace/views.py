import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import dumps
from ..identity import location
from .store import allowed_chats, legacy_paused, read


def candidates(db, q="", page=1):
    if len(q) > 100 or page < 1 or page > 10000:
        raise ValueError("workspace_invalid_query")
    ids = [v["id"] for v in allowed_chats(db)]
    rows = db.rows(
        "SELECT DISTINCT m.sender_id source_id,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),'姓名待同步') name FROM messages m LEFT JOIN identity_metadata i ON i.account_id=? AND i.source_id=m.sender_id WHERE m.conversation_id IN (SELECT value FROM json_each(?)) AND m.direction='incoming' AND m.sender_id NOT IN ('unknown','',?) AND m.sender_id NOT LIKE '%@chatroom' AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=? AND e.source_id=m.sender_id) ORDER BY name,m.sender_id",
        (
            db.settings.source_account,
            dumps(ids),
            db.settings.source_account,
            db.settings.source_account,
        ),
    )
    rows = [r for r in rows if q in r["name"] or q in r["source_id"]]
    return {
        "items": rows[(page - 1) * 50 : page * 50],
        "total": len(rows),
        "page": page,
        "has_more": len(rows) > page * 50,
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
    doc["can_followup"] = bool(
        doc["body"]["relationship"] == "merchant"
        and not doc["body"]["paused"]
        and locator["quality"] == "named"
        and doc["body"]["coverage"]["complete_context"]
        and not doc["needs_update"]
    )
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    doc["today_action_ids"] = [
        k
        for k, a in doc["body"]["actions"].items()
        if doc["can_followup"]
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
