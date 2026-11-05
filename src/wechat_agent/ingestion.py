import hashlib
from contextlib import nullcontext
from datetime import UTC

from .db import DB, dumps, now, uid
from .schemas import Message


def enqueue(c, conversation_id, message_ids=None):
    if message_ids is None:
        rows = c.execute(
            "SELECT id,revision FROM messages WHERE conversation_id=? ORDER BY event_time,id",
            (conversation_id,),
        ).fetchall()
    else:
        selected = list(set(message_ids))
        if not selected:
            return
        rows = c.execute(
            "SELECT id,revision FROM messages WHERE conversation_id=? AND id IN ("
            + ",".join("?" for _ in selected)
            + ") ORDER BY event_time,id",
            (conversation_id, *selected),
        ).fetchall()
    rows = [tuple(x) for x in rows]
    roles = [
        tuple(r)
        for r in c.execute(
            "SELECT sender_id,role,display_name FROM contact_roles WHERE conversation_id=? ORDER BY sender_id",
            (conversation_id,),
        )
    ]
    binding = tuple(
        c.execute(
            "SELECT merchant_id,project_id,egress FROM conversations WHERE id=?",
            (conversation_id,),
        ).fetchone()
    )
    for offset in range(0, len(rows), 30):
        chunk = rows[offset : offset + 30]
        key = hashlib.sha256(
            dumps([conversation_id, chunk, binding, roles, "extract-v1"]).encode()
        ).hexdigest()
        c.execute(
            "INSERT OR IGNORE INTO jobs(id,dedup_key,payload,available_at,created_at) VALUES(?,?,?,?,?)",
            (
                uid(),
                key,
                dumps(
                    {
                        "conversation_id": conversation_id,
                        "message_ids": [r[0] for r in chunk],
                    }
                ),
                now(),
                now(),
            ),
        )


def ingest(
    db: DB, records: list[dict], preview=False, *, analyze=True, connection=None
):
    if len(records) > 1000:
        raise ValueError("单批最多 1000 条")
    messages = [
        Message.model_validate(x) for x in records
    ]  # All-or-nothing validation.
    counts = dict(inserted=0, duplicates=0, revised=0, excluded=0)
    with db.tx() if connection is None else nullcontext(connection) as c:
        changed = {}
        for m in messages:
            chat = c.execute(
                "SELECT * FROM conversations WHERE source=? AND account_id=? AND source_id=?",
                (m.source, m.account_id, m.conversation_id),
            ).fetchone()
            if chat is None or not chat["allowlisted"]:
                counts["excluded"] += 1
                continue
            if chat["kind"] != m.conversation_type:
                raise ValueError("会话类型不匹配")
            existing = c.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND source_id=?",
                (chat["id"], m.source_id),
            ).fetchone()
            stamp = m.event_time.astimezone(UTC).isoformat()
            if existing:
                same = all(
                    existing[k] == v
                    for k, v in {
                        "text": m.text,
                        "completeness": m.completeness,
                        "type": m.message_type,
                        "sender_id": m.sender_id,
                        "direction": m.direction,
                        "event_time": stamp,
                        "source_locator": dumps(m.source_locator),
                    }.items()
                )
                if same:
                    counts["duplicates"] += 1
                else:
                    counts["revised"] += 1
                    if not preview:
                        c.execute(
                            "INSERT INTO message_revisions VALUES(?,?,?,?,?)",
                            (
                                uid(),
                                existing["id"],
                                existing["revision"],
                                existing["text"],
                                now(),
                            ),
                        )
                        c.execute(
                            "UPDATE messages SET text=?,completeness=?,type=?,sender_id=?,direction=?,event_time=?,source_locator=?,revision=revision+1 WHERE id=?",
                            (
                                m.text,
                                m.completeness,
                                m.message_type,
                                m.sender_id,
                                m.direction,
                                stamp,
                                dumps(m.source_locator),
                                existing["id"],
                            ),
                        )
                        c.execute(
                            "DELETE FROM attachments WHERE message_id=?",
                            (existing["id"],),
                        )
                        changed.setdefault(chat["id"], set()).add(m.source_id)
            else:
                counts["inserted"] += 1
                if not preview:
                    c.execute(
                        "INSERT INTO messages(id,conversation_id,source_id,sender_id,direction,event_time,text,type,completeness,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            uid(),
                            chat["id"],
                            m.source_id,
                            m.sender_id,
                            m.direction,
                            stamp,
                            m.text,
                            m.message_type,
                            m.completeness,
                            now(),
                        ),
                    )
                    c.execute(
                        "UPDATE messages SET source_locator=? WHERE conversation_id=? AND source_id=?",
                        (dumps(m.source_locator), chat["id"], m.source_id),
                    )
                    changed.setdefault(chat["id"], set()).add(m.source_id)
        for chat_id in changed:
            # New input invalidates unreviewed results, never confirmed tasks.
            c.execute(
                "UPDATE suggestions SET status='stale' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE json_extract(payload,'$.conversation_id')=?)",
                (chat_id,),
            )
            if not analyze:
                continue
            ids = [
                r["id"]
                for r in c.execute(
                    "SELECT id,source_id FROM messages WHERE conversation_id=? AND source_id IN ("
                    + ",".join("?" for _ in changed[chat_id])
                    + ")",
                    (chat_id, *changed[chat_id]),
                )
                if r["source_id"] in changed[chat_id]
            ]
            policy = c.execute(
                "SELECT enabled FROM crm_policies WHERE account_id=(SELECT account_id FROM conversations WHERE id=?)",
                (chat_id,),
            ).fetchone()
            if not policy:
                enqueue(c, chat_id, ids)
    if connection is None and analyze and not preview and changed:
        from .crm import schedule

        schedule(db)
    return counts
