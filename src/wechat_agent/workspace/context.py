"""Bounded cross-conversation evidence retrieval without legacy model memory."""

import json
import re
from datetime import UTC, datetime

from ..db import dumps
from .store import allowed_chats, eligible, legacy_paused, raw, stable, valid_refs


def related_chats(db, source_id):
    return [
        v
        for v in allowed_chats(db)
        if (v["kind"] == "private" and v["source_id"] == source_id)
        or (
            v["kind"] == "group"
            and db.rows(
                "SELECT 1 FROM messages WHERE conversation_id=? AND sender_id=? LIMIT 1",
                (v["id"], source_id),
            )
        )
    ]


def snapshot(db, source_id, include_document=True):
    chats = related_chats(db, source_id)
    ids = [v["id"] for v in chats]
    rows = db.rows(
        "SELECT id,revision FROM messages WHERE conversation_id IN (SELECT value FROM json_each(?)) ORDER BY id",
        (dumps(ids),),
    )
    doc = raw(db, source_id)
    policy = db.rows(
        "SELECT * FROM crm_policies WHERE account_id=?", (db.settings.source_account,)
    )
    exclusions = db.rows(
        "SELECT * FROM actor_exclusions WHERE account_id=? ORDER BY source_id",
        (db.settings.source_account,),
    )
    return stable(
        chats,
        rows,
        policy,
        exclusions,
        legacy_paused(db, source_id),
        doc["version"] if doc and include_document else 0,
    )


def build(db, source_id, search=None):
    eligible(db, source_id)
    selected = {}
    complete = True
    for chat in related_chats(db, source_id):
        if chat["kind"] == "private" and chat["source_id"] != source_id:
            continue
        if chat["kind"] == "group" and not db.rows(
            "SELECT 1 FROM messages WHERE conversation_id=? AND sender_id=? LIMIT 1",
            (chat["id"], source_id),
        ):
            continue
        rows = db.rows(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY event_time DESC,id DESC LIMIT 501",
            (chat["id"],),
        )
        if len(rows) > 500:
            complete = False
        rows = list(reversed(rows[:500]))
        anchors = [
            i
            for i, m in enumerate(rows)
            if chat["kind"] == "private" or m["sender_id"] == source_id
        ]
        positions = range(len(rows))
        for i in positions:
            m = rows[i]
            if m["type"] != "text" or m["completeness"] != "full":
                complete = False
                continue
            if search and search not in m["text"]:
                continue
            selected[m["id"]] = m | {
                "anchor": i in anchors,
                "event_time": datetime.fromisoformat(m["event_time"])
                .astimezone(UTC)
                .isoformat(),
            }
    rows = sorted(
        selected.values(), key=lambda m: (m["event_time"], m["id"]), reverse=True
    )
    kept = []
    size = 0
    for m in rows:
        if len(kept) >= 80 or size + len(m["text"]) > 16000:
            complete = False
            break
        kept.append(m)
        size += len(m["text"])
    metadata = db.rows(
        "SELECT remark,nickname,alias FROM identity_metadata WHERE account_id=?",
        (db.settings.source_account,),
    )
    replacements = {v for r in metadata for v in r.values() if v}
    replacements.update(v["title"] for v in allowed_chats(db) if v["title"])

    def redact(value):
        for name in sorted(replacements, key=len, reverse=True):
            value = value.replace(name, "[名称]")
        value = re.sub(
            r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|wxid_[\w-]+",
            "[隐去]",
            value,
        )
        return value

    evidence = {stable("evidence", m["id"], m["revision"]): m for m in reversed(kept)}
    document = raw(db, source_id)
    memory = (
        json.loads(document["body"])
        if document and valid_refs(db, json.loads(document["read_set"]))
        else None
    )

    # IDs remain stable aliases; source names and raw account IDs stay local.
    def clean(value):
        if isinstance(value, dict):
            return {
                k: redact(v)
                if k in {"text", "reason", "resolution"} and isinstance(v, str)
                else clean(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    memory = clean(memory)
    payload = {
        "customer": "CUSTOMER",
        "timezone": "Asia/Shanghai",
        "document": memory,
        "complete_context": complete,
        "messages": [
            {
                "ref": ref,
                "actor": "SELF"
                if m["direction"] == "outgoing"
                else "CUSTOMER"
                if m["sender_id"] == source_id
                else stable("actor", m["sender_id"]),
                "time": m["event_time"],
                "text": redact(m["text"]),
            }
            for ref, m in evidence.items()
        ],
    }
    return {"payload": payload, "evidence": evidence, "complete": complete}
