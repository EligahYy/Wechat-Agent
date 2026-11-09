"""Read every authorized source packet before synthesizing a customer document."""

import json

from ..db import dumps, now
from .quality import ENGINE_VERSION
from .schema import FactBook
from .store import reference, stable
from .transport import FactbookError

EXTRACT = """按客户归集资料。输入是同一相关会话按时间排列的完整分片，保留上下文、疑问、回答、报价、货品、时间、承诺、订单和运输进展。不要以价值判断过滤，也不要只提待办。群里其他人的事实保留subject=other或unclear，不能都归给CUSTOMER。
区分问题/计划/实际状态；客户问没发出去不代表未发货，后续发出去了/已发车/已出境是实际已走货，系统出库可能滞后。订单号原样保留。媒体占位只记内容未知，不能猜图。
每条fact.evidence必须引用当前分片messages.ref。尽量保留各个不同事实、状态变化、原始日期与未解决问题，信息少的闲聊可归入context。没有业务理解把握时原意保留，不删除。文本不要出现内部actor哈希。
严格JSON：""" + dumps(FactBook.model_json_schema())
MERGE = """你在合并同一客户的资料分册，尚未生成CRM行动。合并相同事实，保留各订单的状态变化、后续回复、新旧需求、未解决承诺、分歧、其他参与人的不同归属及所有关键证据。不能用较早的疑问覆盖后续实际发货。不要因为不明业务而删除事实，不要把不同订单合成一批。evidence仅可引用输入facts已有的来源ref，subject不明保持unclear。所有输入分册的原始fact已保留，不需复述闲聊但不能丢失已发货/新需求等业务事实。
JSON：""" + dumps(FactBook.model_json_schema())


def groups(items, limit=10000, count=32):
    current, size = [], 0
    for item in items:
        n = len(dumps(item))
        if n > 60000:
            raise ValueError("workspace_source_too_large")
        if current and (size + n > limit or len(current) >= count):
            yield current
            current, size = [], 0
        current.append(item)
        size += n
    if current:
        yield current


def progress(
    db,
    source_id,
    fingerprint,
    total,
    completed,
    source_count,
    processed,
    status="running",
    phase="collect",
    error=None,
):
    with db.tx() as c:
        c.execute(
            "INSERT INTO workspace_scans VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET fingerprint=excluded.fingerprint,status=excluded.status,phase=excluded.phase,total_pages=excluded.total_pages,completed_pages=excluded.completed_pages,source_messages=excluded.source_messages,processed_messages=excluded.processed_messages,error=excluded.error,updated_at=excluded.updated_at",
            (
                db.settings.source_account,
                source_id,
                fingerprint,
                status,
                phase,
                total,
                completed,
                source_count,
                processed,
                error,
                now(),
            ),
        )


def prepare(db, source_id, context, session):
    evidence = context["evidence"]
    # Conversation boundaries and chronological order are retained. No value filter.
    by_chat = {}
    for msg in context["payload"]["messages"]:
        by_chat.setdefault(evidence[msg["ref"]]["conversation_id"], []).append(msg)
    pages = [p for messages in by_chat.values() for p in groups(messages)]
    total, completed, processed = len(pages), 0, 0
    fingerprint = session.fingerprint
    progress(db, source_id, fingerprint, total, 0, len(evidence), 0)

    def packet(kind, payload, prompt):
        session.ensure_active()
        key = stable(
            ENGINE_VERSION,
            db.settings.model,
            db.settings.source_account,
            source_id,
            kind,
            payload,
        )
        saved = db.rows("SELECT body FROM workspace_packets WHERE cache_key=?", (key,))
        if saved:
            return json.loads(saved[0]["body"])
        try:
            book = session.factbook(prompt, payload)
            body = book.model_dump()
        except FactbookError:
            field = "messages" if kind == "extract" else "facts"
            items = payload[field]
            if len(items) < 2:
                raise
            # Split only the failing packet. Validated children survive pauses and
            # retries; the original archive and every extracted packet stay intact.
            middle = len(items) // 2
            children = [
                packet(kind, payload | {field: part}, prompt)
                for part in (items[:middle], items[middle:])
            ]
            body = {"facts": [f for child in children for f in child["facts"]]}
        # Hard checks only for invented source refs; no numeric/term deletion.
        allowed = {m["ref"] for m in payload.get("messages", [])} or {
            r for f in payload.get("facts", []) for r in f["evidence"]
        }
        for fact in body["facts"]:
            if any(r not in allowed for r in fact["evidence"]):
                raise ValueError("workspace_unknown_evidence")
        if not body["facts"] and (payload.get("messages") or payload.get("facts")):
            raise ValueError("workspace_empty_factbook")
        refs = [reference(evidence[r]) for r in sorted(allowed)]
        with db.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO workspace_packets VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    db.settings.source_account,
                    source_id,
                    kind,
                    dumps(refs),
                    dumps(body),
                    now(),
                ),
            )
        return body

    books = []
    for page in pages:
        payload = {"phase": "extract", "customer": "CUSTOMER", "messages": page}
        books.append(packet("extract", payload, EXTRACT))
        completed += 1
        processed += len(page)
        progress(db, source_id, fingerprint, total, completed, len(evidence), processed)
    facts = [f for book in books for f in book["facts"]]
    level = 0
    while len(dumps(facts)) > 16000:
        level += 1
        if level > 8:
            raise ValueError("workspace_summary_limit")
        progress(
            db,
            source_id,
            fingerprint,
            total,
            completed,
            len(evidence),
            processed,
            phase="merge",
        )
        merged = []
        # Leave ample output room for evidence and order identifiers. A hundred
        # verbose facts previously overflowed the default 4000-token response.
        for part in groups(facts, limit=6000, count=16):
            merged.extend(
                packet(
                    "merge",
                    {"phase": "merge", "format": 2, "level": level, "facts": part},
                    MERGE,
                )["facts"]
            )
        if len(dumps(merged)) >= len(dumps(facts)):
            raise ValueError("workspace_summary_not_reduced")
        facts = merged
    progress(
        db,
        source_id,
        fingerprint,
        total,
        completed,
        len(evidence),
        processed,
        phase="summarize",
    )
    context["pages"] = total
    context["processed_messages"] = processed
    # Final synthesis uses the complete packet summaries and their original refs.
    # Full originals stay in SQLite and in context.evidence for field validation.
    cited = {r for f in facts for r in f["evidence"]}
    messages = [m for m in context["payload"]["messages"] if m["ref"] in cited]
    payload = context["payload"] | {
        "phase": "synthesize",
        "facts": facts,
        "messages": messages,
    }
    if len(dumps(payload)) > 85000:
        # Facts retain evidence refs; excerpts are visibly marked, never silently
        # counted as a full raw reread in the final stage.
        payload["messages"] = [
            m | {"text": m["text"][:400], "excerpted": len(m["text"]) > 400}
            for m in messages
        ]
    return payload
