"""Customer follow-up eligibility; exemptions retain local archive."""

import json

from .db import now


def allowed_evidence(db, encoded):
    refs = json.loads(encoded) if isinstance(encoded, str) else encoded
    if not refs:
        return False
    return all(
        db.rows(
            "SELECT 1 FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id=? AND m.revision=? AND v.account_id=? AND v.allowlisted=1 AND v.egress=1 AND v.followup_source=1",
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
        "SELECT v.id,v.title,v.kind,v.source_id,v.followup_source,(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=v.id) messages FROM conversations v WHERE "
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
            "SELECT id FROM conversations WHERE account_id=? AND allowlisted=1 AND id IN ("
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
        db.event(
            c,
            db.settings.source_account,
            "followup_scope_updated",
            {"conversation_ids": ids, "enabled": enabled},
        )
    from .crm import schedule

    schedule(db)
    return {"ok": True, "changed": len(ids), "counts": counts(db)}
