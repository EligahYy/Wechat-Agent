"""Account-scoped analysis diagnostics without exposing chat text or credentials."""

import json
from datetime import UTC, datetime, timedelta

from .analysis import budget_state
from .crm import TZ
from .db import now
from .planning import DAYS, PLANNER, gate, inventory


def overview(db):
    account = db.settings.source_account
    c = db.connect()
    try:
        rows, _, jobs, covered, filtered = inventory(c, account)
    finally:
        c.close()
    policy = db.rows("SELECT * FROM crm_policies WHERE account_id=?", (account,))
    cutoff = (datetime.now(UTC) - timedelta(days=DAYS)).isoformat()
    excluded = {
        r["entity_id"]
        for r in db.rows(
            "SELECT e.entity_id,e.payload FROM events e JOIN conversations v ON v.id=e.entity_id WHERE v.account_id=? AND e.kind='crm_scope_change' AND e.created_at=(SELECT MAX(e2.created_at) FROM events e2 WHERE e2.entity_id=e.entity_id AND e2.kind='crm_scope_change')",
            (account,),
        )
        if not json.loads(r["payload"])["enabled"]
    }
    eligible = [
        r for r in rows if r["allowlisted"] and r["conversation_id"] not in excluded
    ]
    scopes = {}
    for scope in ("recent", "history"):
        selected = [
            r for r in eligible if (r["event_time"] >= cutoff) == (scope == "recent")
        ]
        analyzed = sum(r["id"] in covered for r in selected)
        skipped = sum(r["id"] in filtered for r in selected)
        scopes[scope] = {
            "total": len(selected),
            "analyzed": analyzed,
            "filtered": skipped,
            "pending": len(selected) - analyzed - skipped,
            "percent": round((analyzed + skipped) * 100 / len(selected), 1)
            if selected
            else 0,
        }
    states = {}
    for job in jobs:
        p = json.loads(job["payload"])
        if p.get("planner") == PLANNER and job["status"] != "superseded":
            states[job["status"]] = states.get(job["status"], 0) + 1
    daily = db.rows(
        "SELECT day,COUNT(*) calls,SUM(COALESCE(actual,0)) reported,SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END) uncertain FROM usage WHERE day>=? GROUP BY day ORDER BY day",
        ((datetime.now(TZ) - timedelta(days=6)).date().isoformat(),),
    )
    outcomes = db.rows(
        "SELECT substr(e.created_at,1,10) day,SUM(json_extract(e.payload,'$.status')='succeeded') completed,COUNT(*) attempts FROM events e JOIN jobs j ON j.id=e.entity_id JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE e.kind='analysis_outcome' AND v.account_id=? AND e.created_at>=? GROUP BY substr(e.created_at,1,10) ORDER BY day",
        (account, (datetime.now(UTC) - timedelta(days=7)).isoformat()),
    )
    failures = db.rows(
        "SELECT j.error,COUNT(*) n FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE v.account_id=? AND j.status IN ('failed','retry_wait','blocked_credentials','blocked_budget','blocked_context_limit','waiting_history_budget') AND COALESCE(json_extract(j.payload,'$.planner'),0)=? GROUP BY j.error",
        (account, PLANNER),
    )
    totals = db.rows(
        "SELECT COUNT(*) total,SUM(m.type<>'text') media,SUM(m.type='text' AND m.completeness<>'full') partial FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=?",
        (account,),
    )[0]
    counts = {
        table: db.rows(
            f"SELECT COUNT(*) n FROM {table} WHERE account_id=?", (account,)
        )[0]["n"]
        for table in ("crm_customers", "crm_reviews")
    }
    actions = db.rows(
        "SELECT COUNT(*) n FROM crm_actions a JOIN crm_customers u ON u.id=a.customer_id WHERE u.account_id=?",
        (account,),
    )[0]["n"]
    return {
        "updated_at": now(),
        "account_name": db.settings.source_name or account,
        "account_id": account,
        "recent_days": DAYS,
        "recent_since": cutoff,
        "scope": scopes,
        "queue": states,
        "gate": gate(db),
        "budget": budget_state(db),
        "daily_usage": daily,
        "outcomes": outcomes,
        "failures": failures,
        "messages": totals,
        "customers": counts["crm_customers"],
        "actions": actions,
        "reviews": counts["crm_reviews"],
        "runtime": [
            r
            for r in db.rows("SELECT * FROM runtime")
            if not r["name"].startswith(("model_gate:", "model_history_gate:"))
        ],
        "enabled": bool(policy and policy[0]["enabled"]),
        "history_reserve_percent": 20,
    }


def job_page(db, scope="all", status="all", page=1):
    if (
        scope not in {"all", "recent", "history"}
        or status not in {"all", "pending", "running", "issues", "complete"}
        or not 1 <= page <= 100000
    ):
        raise ValueError("分析查询参数无效")
    conditions = [
        "v.account_id=?",
        "json_extract(j.payload,'$.planner')=?",
        "j.status<>'superseded'",
    ]
    args = [db.settings.source_account, PLANNER]
    if scope != "all":
        conditions.append("json_extract(j.payload,'$.scope')=?")
        args.append(scope)
    groups = {
        "pending": "('queued','deferred_recent','deferred_history','retry_wait','blocked_budget','waiting_history_budget')",
        "running": "('running')",
        "issues": "('failed','retry_wait','blocked_credentials','blocked_budget','blocked_context_limit','waiting_history_budget','stale_input')",
        "complete": "('succeeded','filtered_noise')",
    }
    if status != "all":
        conditions.append("j.status IN " + groups[status])
    where = " AND ".join(conditions)
    total = db.rows(
        "SELECT COUNT(*) n FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE "
        + where,
        args,
    )[0]["n"]
    rows = db.rows(
        "SELECT j.id,j.payload,j.status,j.attempts,j.error,j.available_at,j.created_at,v.title conversation_title,(SELECT MAX(e.created_at) FROM events e WHERE e.entity_id=j.id AND e.kind='analysis_outcome') updated_at,(SELECT SUM(u.actual) FROM usage u WHERE u.job_id=j.id) reported_tokens,(SELECT SUM(CASE WHEN u.actual IS NULL THEN u.reserved ELSE 0 END) FROM usage u WHERE u.job_id=j.id) uncertain_tokens FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE "
        + where
        + " ORDER BY j.status='running' DESC,COALESCE(json_extract(j.payload,'$.priority'),0),j.created_at DESC LIMIT 30 OFFSET ?",
        [*args, (page - 1) * 30],
    )
    for r in rows:
        p = json.loads(r.pop("payload"))
        r.update(
            scope=p.get("scope"),
            message_count=len(p.get("primary_ids", [])),
            range_start=p.get("range_start"),
            range_end=p.get("range_end"),
        )
    return {"items": rows, "total": total, "page": page, "has_more": page * 30 < total}
