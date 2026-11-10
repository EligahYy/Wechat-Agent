"""Source identity enrichment. Display labels never become stable identifiers."""

import re

from .db import now


def clean_name(value, source_id):
    return re.sub(r"\s*[（(]" + re.escape(source_id) + r"[）)]$", "", value).strip()


def is_group_source(c, account, source_id):
    """Classify stable source identities, never display names."""
    return source_id.endswith("@chatroom") or bool(
        c.execute(
            "SELECT 1 FROM conversations WHERE account_id=? AND source_id=? AND kind='group'",
            (account, source_id),
        ).fetchone()
    )


def save_display(db, account, source_id, display):
    name = clean_name(display, source_id)
    if not name or name == source_id:
        return
    with db.tx() as c:
        c.execute(
            "INSERT INTO identity_metadata(account_id,source_id,nickname,updated_at) VALUES(?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET nickname=CASE WHEN identity_metadata.nickname='' THEN excluded.nickname ELSE identity_metadata.nickname END",
            (account, source_id, name, now()),
        )


def sync_contacts(db, source):
    source.validate()
    items, seen = [], set()
    for offset in range(0, 20000, 100):
        response = source.client.get(
            "/api/v1/contacts", params={"limit": 100, "offset": offset}
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("items"), list):
            raise ValueError("contacts_schema_incompatible")
        added = 0
        for item in data["items"]:
            row = item.get("contact", item)
            sid = row.get("user_name")
            if not isinstance(sid, str) or not sid:
                raise ValueError("contact_identity_missing")
            if sid not in seen:
                added += 1
                seen.add(sid)
                items.append(
                    (
                        db.settings.source_account,
                        sid,
                        *[
                            (
                                clean_name(row[k], sid)
                                if k != "alias" and clean_name(row[k], sid) != sid
                                else row[k]
                                if k == "alias"
                                else ""
                            )
                            if isinstance(row.get(k), str)
                            else ""
                            for k in ("remark", "nick_name", "alias")
                        ],
                        now(),
                    )
                )
        more = data.get("paging", {}).get("has_more")
        if type(more) is not bool:
            raise ValueError("contacts_paging_unavailable")
        if not more:
            break
        if not added:
            raise ValueError("contacts_pagination_stalled")
    else:
        raise ValueError("contacts_limit")
    source.validate()
    with db.tx() as c:
        c.executemany(
            "INSERT INTO identity_metadata VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET remark=excluded.remark,nickname=excluded.nickname,alias=excluded.alias,updated_at=excluded.updated_at",
            items,
        )
        c.execute(
            "UPDATE conversations SET title=(SELECT CASE WHEN i.remark<>'' THEN i.remark ELSE i.nickname END FROM identity_metadata i WHERE i.account_id=conversations.account_id AND i.source_id=conversations.source_id) WHERE account_id=? AND EXISTS(SELECT 1 FROM identity_metadata i WHERE i.account_id=conversations.account_id AND i.source_id=conversations.source_id AND (i.remark<>'' OR i.nickname<>''))",
            (db.settings.source_account,),
        )
    db.heartbeat("identity", "running")
    return {"ok": True, "contacts": len(items)}


def location(db, source_id):
    account = db.settings.source_account
    rows = db.rows(
        "SELECT * FROM identity_metadata WHERE account_id=? AND source_id=?",
        (account, source_id),
    )
    metadata = rows[0] if rows else {}
    chats = db.rows(
        "SELECT DISTINCT v.id,v.title,v.kind FROM conversations v LEFT JOIN messages m ON m.conversation_id=v.id WHERE v.account_id=? AND ((v.kind='private' AND v.source_id=?) OR m.sender_id=?) ORDER BY v.kind='private' DESC,v.title LIMIT 8",
        (account, source_id, source_id),
    )
    return {
        "remark": metadata.get("remark", ""),
        "nickname": metadata.get("nickname", ""),
        "alias": metadata.get("alias", ""),
        "conversations": chats,
        "quality": "named"
        if metadata.get("remark") or metadata.get("nickname")
        else "conversation_only"
        if chats
        else "unavailable",
    }


def set_excluded(db, actor_id, enabled, reason):
    if type(enabled) is not bool or not isinstance(reason, str) or len(reason) > 200:
        raise ValueError("排除参数无效")
    rows = db.rows(
        "SELECT source_id FROM crm_contacts WHERE id=? AND account_id=?",
        (actor_id, db.settings.source_account),
    )
    if not rows:
        raise ValueError("联系人不存在")
    with db.tx() as c:
        if is_group_source(c, db.settings.source_account, rows[0]["source_id"]):
            raise ValueError("这是群聊会话，请在会话白名单中管理")
        if (
            not enabled
            and c.execute(
                "SELECT 1 FROM effective_actor_exclusions WHERE account_id=? AND source_id=? AND origin='group'",
                (db.settings.source_account, rows[0]["source_id"]),
            ).fetchone()
        ):
            raise ValueError("此人随白名单群免跟进，请先恢复所属群")
        if enabled:
            c.execute(
                "INSERT INTO actor_exclusions VALUES(?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET reason=excluded.reason",
                (db.settings.source_account, rows[0]["source_id"], reason),
            )
        else:
            c.execute(
                "DELETE FROM actor_exclusions WHERE account_id=? AND source_id=?",
                (db.settings.source_account, rows[0]["source_id"]),
            )
            c.execute(
                "UPDATE conversations SET followup_source=1 WHERE account_id=? AND source_id=? AND kind='private'",
                (db.settings.source_account, rows[0]["source_id"]),
            )
        db.event(
            c, actor_id, "person_exclusion", {"enabled": enabled, "reason": reason}
        )
    return {"ok": True}


def audit(db):
    rows = db.rows(
        "SELECT n.source_id,n.name FROM crm_contacts n WHERE n.account_id=? AND n.source_id NOT LIKE '%@chatroom' AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.account_id=n.account_id AND v.source_id=n.source_id AND v.kind='group')",
        (db.settings.source_account,),
    )
    unresolved = sum(
        r["name"].startswith("群聊联系人 · ") or r["name"] == r["source_id"]
        for r in rows
    )
    return {
        "contacts": len(rows),
        "unresolved_names": unresolved,
        "metadata": db.rows(
            "SELECT COUNT(*) n FROM identity_metadata WHERE account_id=?",
            (db.settings.source_account,),
        )[0]["n"],
        "note": "仅统计本机身份数据，不调用模型、不修改客户或任务。",
    }
