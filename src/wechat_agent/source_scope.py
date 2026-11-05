"""Customer follow-up eligibility; exemptions retain local archive."""

import json

from .db import dumps, now, uid


def allowed_evidence(db, encoded):
    refs = json.loads(encoded) if isinstance(encoded, str) else encoded
    if not refs:
        return False
    return all(
        db.rows(
            "SELECT 1 FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id=? AND m.revision=? AND v.account_id=? AND v.allowlisted=1 AND v.egress=1 AND v.followup_source=1 AND NOT EXISTS (SELECT 1 FROM conversation_classifications k WHERE k.conversation_id=v.id AND k.kind IN ('internal','buyer','provider','announcement'))",
            (ref["id"], ref["revision"], db.settings.source_account),
        )
        for ref in refs
    )


def counts(db):
    row = db.rows(
        "SELECT COUNT(*) total,COALESCE(SUM(followup_source),0) selected FROM conversations WHERE account_id=? AND allowlisted=1",
        (db.settings.source_account,),
    )[0]
    return row | {"archive_only": row["total"] - row["selected"]}


def list_sources(db, q="", kind="all", scope="all", page=1):
    if (
        not isinstance(q, str)
        or len(q) > 200
        or kind not in {"all", "group", "private"}
        or scope not in {"all", "customer", "archive"}
        or not 1 <= page <= 100000
    ):
        raise ValueError("会话筛选参数无效")
    where = "v.account_id=? AND v.allowlisted=1"
    args = [db.settings.source_account]
    if q:
        where += " AND (instr(v.title,?)>0 OR instr(v.source_id,?)>0)"
        args.extend([q, q])
    if kind != "all":
        where += " AND v.kind=?"
        args.append(kind)
    if scope != "all":
        where += " AND v.followup_source=?"
        args.append(int(scope == "customer"))
    total = db.rows("SELECT COUNT(*) n FROM conversations v WHERE " + where, args)[0][
        "n"
    ]
    rows = db.rows(
        "SELECT v.id,v.title,v.kind,v.source_id,v.followup_source,(SELECT kind FROM conversation_classifications WHERE conversation_id=v.id) business_kind,(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=v.id) messages FROM conversations v WHERE "
        + where
        + " ORDER BY v.followup_source ASC,v.title,v.id LIMIT 50 OFFSET ?",
        [*args, (page - 1) * 50],
    )
    return {
        "items": rows,
        "total": total,
        "has_more": page * 50 < total,
        "page": page,
        "counts": counts(db),
    }


def set_sources(db, ids, enabled):
    if (
        type(enabled) is not bool
        or not isinstance(ids, list)
        or not ids
        or len(ids) > 500
        or any(not isinstance(i, str) for i in ids)
    ):
        raise ValueError("请选择1–500个会话并指定是否加入白名单")
    ids = list(dict.fromkeys(ids))
    marks = ",".join("?" for _ in ids)
    with db.tx() as c:
        rows = c.execute(
            "SELECT id,followup_source,egress FROM conversations WHERE account_id=? AND allowlisted=1 AND id IN ("
            + marks
            + ")",
            (db.settings.source_account, *ids),
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("存在未绑定当前工作账号或已暂停采集的会话，本次未更改")
        policy = c.execute(
            "SELECT enabled FROM crm_policies WHERE account_id=?",
            (db.settings.source_account,),
        ).fetchone()
        grant = int(bool(enabled and policy and policy["enabled"]))
        c.execute(
            "UPDATE conversations SET followup_source=?,egress=CASE WHEN ?=1 THEN 1 ELSE egress END WHERE id IN ("
            + marks
            + ")",
            (int(enabled), grant, *ids),
        )
        if not enabled:
            c.execute(
                "UPDATE jobs SET status='excluded_source',lease_until=NULL,error='followup_exempted' WHERE json_extract(payload,'$.conversation_id') IN ("
                + marks
                + ") AND status NOT IN ('succeeded','filtered_noise','superseded','excluded_source')",
                ids,
            )
        else:
            for cid in ids:
                db.event(c, cid, "crm_scope_change", {"enabled": True})
            c.execute(
                "UPDATE jobs SET status='deferred_'||COALESCE(json_extract(payload,'$.scope'),'recent'),attempts=0,error=NULL,available_at=? WHERE json_extract(payload,'$.conversation_id') IN ("
                + marks
                + ") AND json_extract(payload,'$.planner')=3 AND status='excluded_source'",
                (now(), *ids),
            )
        undo_id = uid()
        c.execute(
            "INSERT INTO events VALUES(?,?,?,?,?)",
            (
                undo_id,
                db.settings.source_account,
                "followup_scope_updated",
                dumps(
                    {
                        "previous": [dict(r) for r in rows],
                        "enabled": enabled,
                        "grant": grant,
                    }
                ),
                now(),
            ),
        )
    from .crm import schedule

    schedule(db)
    return {
        "ok": True,
        "changed": len(ids),
        "counts": counts(db),
        "previous": [dict(r) for r in rows],
        "undo_id": undo_id,
    }


def undo_sources(db, event_id):
    from .crm import schedule

    with db.tx() as c:
        event = c.execute(
            "SELECT payload FROM events WHERE id=? AND entity_id=? AND kind='followup_scope_updated'",
            (event_id, db.settings.source_account),
        ).fetchone()
        if not event:
            raise ValueError("这次操作不可撤销或已撤销")
        saved = json.loads(event["payload"])
        for old in saved["previous"]:
            current = c.execute(
                "SELECT followup_source,egress FROM conversations WHERE id=? AND account_id=?",
                (old["id"], db.settings.source_account),
            ).fetchone()
            expected_egress = 1 if saved["grant"] else old["egress"]
            if (
                not current
                or current["followup_source"] != int(saved["enabled"])
                or current["egress"] != expected_egress
            ):
                raise ValueError("会话范围已再次修改，请刷新后处理")
        for old in saved["previous"]:
            c.execute(
                "UPDATE conversations SET followup_source=?,egress=? WHERE id=?",
                (old["followup_source"], old["egress"], old["id"]),
            )
            if old["followup_source"]:
                c.execute(
                    "UPDATE jobs SET status='deferred_'||COALESCE(json_extract(payload,'$.scope'),'recent'),attempts=0,error=NULL WHERE status='excluded_source' AND json_extract(payload,'$.conversation_id')=? AND json_extract(payload,'$.planner')=3",
                    (old["id"],),
                )
        c.execute(
            "UPDATE events SET kind='followup_scope_undone' WHERE id=?", (event_id,)
        )
    schedule(db)
    return {"ok": True}
