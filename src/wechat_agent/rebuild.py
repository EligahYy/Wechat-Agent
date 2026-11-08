"""Read-only M0 inventory for the replacement engine; no legacy AI conclusions."""

from datetime import UTC, datetime, timedelta


def inspect_sources(db, *, at=None):
    account = db.settings.source_account
    if not account:
        raise ValueError("请先绑定工作微信账号")
    at = at or datetime.now(UTC)
    if at.utcoffset() is None:
        raise ValueError("检查时间必须包含时区")
    cutoff = (at - timedelta(days=15)).isoformat()
    # User scope is authoritative; legacy model conversation classifications are
    # intentionally excluded from the replacement engine's eligibility.
    with db.tx() as c:
        chats = [
            dict(r)
            for r in c.execute(
                "SELECT v.*, EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=v.account_id AND e.source_id=v.source_id) person_exempt FROM conversations v WHERE v.account_id=?",
                (account,),
            )
        ]
        messages = [
            dict(r)
            for r in c.execute(
                "SELECT m.*,v.source_id peer,v.kind FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=?",
                (account,),
            )
        ]
        names = {
            r["source_id"]: dict(r)
            for r in c.execute(
                "SELECT * FROM identity_metadata WHERE account_id=?", (account,)
            )
        }
        excluded = {
            r[0]
            for r in c.execute(
                "SELECT source_id FROM actor_exclusions WHERE account_id=?", (account,)
            )
        }
        quarantined = c.execute(
            "SELECT COUNT(*) FROM archive_quarantine q JOIN conversations v ON v.id=q.conversation_id WHERE v.account_id=?",
            (account,),
        ).fetchone()[0]
    allowed = {
        v["id"]
        for v in chats
        if v["allowlisted"]
        and v["egress"]
        and v["followup_source"]
        and not (v["kind"] == "private" and v["person_exempt"])
    }
    text = [
        m
        for m in messages
        if m["conversation_id"] in allowed
        and m["type"] == "text"
        and m["completeness"] == "full"
    ]
    recent = [
        m
        for m in text
        if datetime.fromisoformat(cutoff)
        <= datetime.fromisoformat(m["event_time"])
        <= at
    ]
    identities = {
        m["sender_id"]
        for m in messages
        if m["direction"] == "incoming"
        and m["sender_id"] not in {"unknown", "", account}
    }
    targets = identities - excluded
    named = {
        sid
        for sid in targets
        if any(names.get(sid, {}).get(k) for k in ("remark", "nickname"))
    }
    return {
        "phase": "M0_inventory",
        "mode": "local_only",
        "model_calls": 0,
        "conversations": {
            "archived": len(chats),
            "eligible": len(allowed),
            "unnamed": sum(
                not v["title"].strip() or v["title"] == v["source_id"] for v in chats
            ),
        },
        "messages": {
            "archived": len(messages),
            "eligible_full_text": len(text),
            "recent_15_days": len(recent),
            "older_text": sum(
                datetime.fromisoformat(m["event_time"]) < datetime.fromisoformat(cutoff)
                for m in text
            ),
            "future_timestamp": sum(
                datetime.fromisoformat(m["event_time"]) > at for m in text
            ),
            "nontext": sum(m["type"] != "text" for m in messages),
            "partial": sum(m["completeness"] != "full" for m in messages),
            "unknown_sender": sum(m["sender_id"] in {"unknown", ""} for m in messages),
            "quarantined": quarantined,
        },
        "identities": {
            "observed": len(identities),
            "exempt": len(excluded),
            "non_exempt_named": len(named),
            "non_exempt_missing_name": len(targets - named),
        },
        "capabilities": {
            "group_member_names": "not_verified",
            "reply_links": "not_verified",
            "attachment_readability": "not_verified",
            "ocr": "not_implemented",
        },
        "note": "仅检查已归档可见数据；人物数不是客户数。未联网探测源端、未重建或清理旧结果。",
    }
