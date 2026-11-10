"""Full authorized customer corpus; originals remain separate from summaries."""

import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..db import dumps
from .order_links import link_index, linked_keys
from .quality import ENGINE_VERSION, MODES
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


def extractions(db, ids):
    return db.rows(
        "SELECT x.message_id,x.version,x.confirmed_text FROM message_extractions x JOIN messages m ON m.id=x.message_id AND m.revision=x.source_revision JOIN attachments a ON a.message_id=m.id AND a.sha256=x.sha256 WHERE x.confirmed_text<>'' AND m.conversation_id IN (SELECT value FROM json_each(?)) ORDER BY x.message_id",
        (dumps(ids),),
    )


def snapshot(db, source_id, include_document=True):
    chats = related_chats(db, source_id)
    ids = [v["id"] for v in chats]
    rows = db.rows(
        "SELECT id,revision FROM messages WHERE conversation_id IN (SELECT value FROM json_each(?)) ORDER BY id",
        (dumps(ids),),
    )
    doc = raw(db, source_id)
    policy = db.rows(
        "SELECT account_id,enabled,include_new,version FROM crm_policies WHERE account_id=?",
        (db.settings.source_account,),
    )
    exclusions = db.rows(
        "SELECT * FROM effective_actor_exclusions WHERE account_id=? ORDER BY source_id,origin,group_source_id",
        (db.settings.source_account,),
    )
    return stable(
        ENGINE_VERSION,
        chats,
        rows,
        [(x["message_id"], x["version"]) for x in extractions(db, ids)],
        policy,
        exclusions,
        legacy_paused(db, source_id),
        doc["version"] if doc and include_document else 0,
    )


def authority(db, source_id):
    # Message additions do not revoke a pinned read. Scope, edits and manual
    # decisions do: they are checked separately before each request/publication.
    doc = raw(db, source_id)
    return stable(
        allowed_chats(db),
        [
            (x["message_id"], x["version"])
            for x in extractions(db, [c["id"] for c in allowed_chats(db)])
        ],
        db.rows(
            "SELECT account_id,enabled,include_new,version FROM crm_policies WHERE account_id=?",
            (db.settings.source_account,),
        ),
        db.rows(
            "SELECT * FROM effective_actor_exclusions WHERE account_id=? ORDER BY source_id,origin,group_source_id",
            (db.settings.source_account,),
        ),
        legacy_paused(db, source_id),
        db.rows(
            "SELECT id FROM events WHERE entity_id=? AND kind='workspace_retry' ORDER BY rowid DESC LIMIT 1",
            ("workspace-retry:" + stable(db.settings.source_account, source_id),),
        ),
        doc["version"] if doc else 0,
    )


def build(db, source_id, search=None):
    eligible(db, source_id)
    selected = {}
    complete = True
    gaps = set()
    source_messages = 0
    chats = related_chats(db, source_id)
    recognized = {x["message_id"]: x for x in extractions(db, [c["id"] for c in chats])}
    for chat in chats:
        if chat["kind"] == "private" and chat["source_id"] != source_id:
            continue
        if chat["kind"] == "group" and not db.rows(
            "SELECT 1 FROM messages WHERE conversation_id=? AND sender_id=? LIMIT 1",
            (chat["id"], source_id),
        ):
            continue
        rows = db.rows(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY event_time DESC,id DESC",
            (chat["id"],),
        )
        source_messages += len(rows)
        rows = list(reversed(rows))
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
                gaps.add("media_or_partial")
            if m["id"] in recognized:
                x = recognized[m["id"]]
                m = m | {
                    "text": m["text"]
                    + "\n[图片文字，已人工核对]\n"
                    + x["confirmed_text"],
                    "extraction_version": x["version"],
                }
            if search and search not in m["text"]:
                continue
            selected[m["id"]] = m | {
                "anchor": i in anchors,
                "event_time": datetime.fromisoformat(m["event_time"])
                .astimezone(UTC)
                .isoformat(),
            }
    kept = sorted(selected.values(), key=lambda m: (m["event_time"], m["id"]))
    metadata = db.rows(
        "SELECT remark,nickname,alias FROM identity_metadata WHERE account_id=?",
        (db.settings.source_account,),
    )
    replacements = {v for r in metadata for v in r.values() if v}
    replacements.update(v["title"] for v in allowed_chats(db) if v["title"])

    def redact(value):
        for name in sorted(replacements, key=len, reverse=True):
            if name in MODES:
                continue  # A business term is not an identity to redact.
            # Avoid replacing a short nickname inside order/warehouse codes.
            if re.fullmatch(r"[A-Za-z0-9_.-]+", name) or len(name) == 1:
                value = re.sub(
                    r"(?<![\w])" + re.escape(name) + r"(?![\w])", "[名称]", value
                )
            else:
                value = value.replace(name, "[名称]")
        value = re.sub(
            r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|wxid_[\w-]+",
            "[隐去]",
            value,
        )
        return value

    evidence = {stable("evidence", m["id"], m["revision"]): m for m in kept}
    order_index = link_index(evidence)
    document = raw(db, source_id)
    memory = (
        json.loads(document["body"])
        if document and valid_refs(db, json.loads(document["read_set"]))
        else None
    )

    if document and memory is None:
        prior = json.loads(document["body"])
        # Human inputs remain constraints even when an old machine citation expires.
        memory = {
            "history": prior.get("history", []),
            "batch_overrides": prior.get("batch_overrides", {}),
            "manual_role": prior.get("manual_role"),
            "notes": {
                ident: item
                for ident, item in prior.get("notes", {}).items()
                if item.get("manual_verified") and valid_refs(db, item["evidence"])
            },
            "clue_resolutions": prior.get("clue_resolutions", {}),
        }
    if memory is not None:
        memory["clue_resolutions"] = {
            ident: {
                "choice": result["choice"],
                "text": memory.get("notes", {})
                .get(result.get("note_id"), {})
                .get("text", result["text"]),
            }
            for ident, result in memory.get("clue_resolutions", {}).items()
            if valid_refs(db, result["original"]["evidence"])
        }

    # IDs remain stable aliases; source names and raw account IDs stay local.
    def clean(value):
        if isinstance(value, dict):
            return {
                k: redact(v)
                if k
                in {
                    "text",
                    "reason",
                    "resolution",
                    "result_note",
                    "impact",
                    "value",
                    "note",
                    "manual_stage_note",
                }
                and isinstance(v, str)
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
        "as_of": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "document": memory,
        "complete_context": complete,
        "messages": [
            {
                "ref": ref,
                "customer_related": bool(m["anchor"]),
                **(
                    {"image_text_version": m["extraction_version"]}
                    if m.get("extraction_version")
                    else {}
                ),
                "content_type": m["type"],
                "completeness": m["completeness"],
                "customer_links": [
                    k for k in linked_keys([ref], evidence, order_index) if k != ref
                ],
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
    return {
        "payload": payload,
        "evidence": evidence,
        "complete": complete,
        "gaps": sorted(gaps),
        "source_messages": source_messages,
    }
