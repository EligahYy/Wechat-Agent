"""Bounded, recent-first scheduling. Queueing is independent of API billing."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from .db import dumps, now, uid
from .message_value import classify

DAYS = 15
BATCH = 8
PLANNER = 3


def fingerprint(cid, rows, corrections, policy_version, legacy=False):
    return hashlib.sha256(
        dumps(
            [
                "crm-v2" if legacy else "crm-v3",
                [corrections.get(r["id"], []) for r in rows],
                cid,
                [(r["id"], r["revision"]) for r in rows],
                policy_version,
            ]
        ).encode()
    ).hexdigest()


def inventory(c, account):
    rows = [
        dict(r)
        for r in c.execute(
            "SELECT m.*,v.title,v.egress,v.allowlisted,v.followup_source FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=? AND m.type='text' AND m.completeness='full' ORDER BY m.event_time,m.id",
            (account,),
        )
    ]
    by_id = {r["id"]: r for r in rows}
    corrections = {}
    for correction in c.execute(
        "SELECT id,resolution,evidence FROM crm_reviews WHERE account_id=? AND status='resolved'",
        (account,),
    ):
        for ref in json.loads(correction["evidence"]):
            corrections.setdefault(ref["id"], []).append(
                (correction["id"], correction["resolution"])
            )
    for fact in c.execute(
        "SELECT f.* FROM crm_facts f JOIN crm_customers u ON u.id=f.customer_id WHERE u.account_id=? AND f.locked=1",
        (account,),
    ):
        for ref in json.loads(fact["evidence"]):
            corrections.setdefault(ref["id"], []).append((fact["id"], fact["value"]))
    covered, filtered = set(), set()
    jobs = [
        dict(r)
        for r in c.execute(
            "SELECT j.* FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE v.account_id=? AND json_extract(j.payload,'$.engine')='crm_v2'",
            (account,),
        )
    ]
    for job in jobs:
        if job["status"] not in {"succeeded", "filtered_noise"}:
            continue
        payload = json.loads(job["payload"])
        selected = [by_id.get(mid) for mid in payload.get("message_ids", [])]
        if not selected or any(r is None for r in selected):
            continue
        key = fingerprint(
            payload["conversation_id"],
            selected,
            corrections,
            payload.get("policy_version"),
            legacy=payload.get("planner") != PLANNER,
        )
        if key != job["dedup_key"]:
            continue
        primary = payload.get("primary_ids", payload["message_ids"])
        (filtered if job["status"] == "filtered_noise" else covered).update(primary)
    return rows, corrections, jobs, covered, filtered


def gate(db, history=False):
    row = db.rows(
        "SELECT status FROM runtime WHERE name=?",
        (
            ("model_history_gate:" if history else "model_gate:")
            + db.settings.source_account,
        ),
    )
    if not row:
        return None
    value = json.loads(row[0]["status"])
    return value if value["until"] > now() else None


def hold(db, reason, until, history=False):
    db.heartbeat(
        ("model_history_gate:" if history else "model_gate:")
        + db.settings.source_account,
        dumps({"reason": reason, "until": until}),
    )


def clear_gate(db):
    with db.tx() as c:
        c.execute(
            "DELETE FROM runtime WHERE name IN (?,?)",
            (
                "model_gate:" + db.settings.source_account,
                "model_history_gate:" + db.settings.source_account,
            ),
        )


def schedule(db, retry=False):
    from .analysis import budget_state
    from .crm import index_contacts, index_touchpoints

    account = db.settings.source_account
    policy = db.rows(
        "SELECT * FROM crm_policies WHERE account_id=? AND enabled=1", (account,)
    )
    if not policy:
        return 0
    if retry:
        clear_gate(db)
    count = 0
    cutoff = (datetime.now(UTC) - timedelta(days=DAYS)).isoformat()
    with db.tx() as c:
        index_contacts(c, account)
        index_touchpoints(c, account)
        rows, corrections, jobs, covered, filtered = inventory(c, account)
        # Old versions left reservations on explicit 401/403 rejections. These
        # can be released with evidence; ambiguous HTTP failures cannot.
        c.execute(
            "UPDATE usage SET actual=0,status='request_rejected' WHERE actual IS NULL AND job_id IN (SELECT j.id FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE v.account_id=? AND j.status='blocked_credentials')",
            (account,),
        )
        # Retain results/audit usage; replace only the old, uncompleted full queue.
        c.execute(
            "UPDATE jobs SET status='superseded',lease_until=NULL,error='planner_replaced' WHERE id IN (SELECT j.id FROM jobs j JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE v.account_id=? AND json_extract(j.payload,'$.engine')='crm_v2' AND COALESCE(json_extract(j.payload,'$.planner'),0)<>? AND j.status NOT IN ('succeeded','superseded'))",
            (account, PLANNER),
        )
        by_chat = {}
        for r in rows:
            if r["egress"] and r["allowlisted"] and r["followup_source"]:
                by_chat.setdefault(r["conversation_id"], []).append(r)
        candidates = []
        for cid, messages in by_chat.items():
            positions = {row["id"]: i for i, row in enumerate(messages)}
            missing = [r for r in messages if r["id"] not in covered | filtered]
            # Do not let a boundary unit pull years of history into a recent batch.
            for scope in ("recent", "history"):
                primary = [
                    r
                    for r in missing
                    if (r["event_time"] >= cutoff) == (scope == "recent")
                ]
                chunks, chunk, size = [], [], 0
                for r in primary:
                    if chunk and (len(chunk) >= 16 or size + len(r["text"]) > 3500):
                        chunks.append(chunk)
                        chunk, size = [], 0
                    chunk.append(r)
                    size += len(r["text"])
                if chunk:
                    chunks.append(chunk)
                for chunk in chunks:
                    start = positions[chunk[0]["id"]]
                    context = messages[max(0, start - 2) : start]
                    selected = context + chunk
                    # Keep context bounded too, but never truncate a source message.
                    while context and sum(len(r["text"]) for r in selected) > 4500:
                        context = context[1:]
                        selected = context + chunk
                    key = fingerprint(cid, selected, corrections, policy[0]["version"])
                    payload = {
                        "engine": "crm_v2",
                        "planner": PLANNER,
                        "conversation_id": cid,
                        "message_ids": [r["id"] for r in selected],
                        "primary_ids": [r["id"] for r in chunk],
                        "policy_version": policy[0]["version"],
                        "scope": scope,
                        "priority": 0 if scope == "recent" else 10,
                        "range_start": chunk[0]["event_time"],
                        "range_end": chunk[-1]["event_time"],
                    }
                    status = (
                        "filtered_noise"
                        if all(classify(r)["value"] == "noise" for r in selected)
                        else "deferred_" + scope
                    )
                    cur = c.execute(
                        "INSERT OR IGNORE INTO jobs(id,dedup_key,payload,status,available_at,created_at) VALUES(?,?,?,?,?,?)",
                        (uid(), key, dumps(payload), status, now(), now()),
                    )
                    count += cur.rowcount
                    if not cur.rowcount:
                        existing = c.execute(
                            "SELECT status,payload FROM jobs WHERE dedup_key=?", (key,)
                        ).fetchone()
                        if existing and existing["status"] not in {
                            "running",
                            "succeeded",
                            "filtered_noise",
                            "superseded",
                        }:
                            old = json.loads(existing["payload"])
                            changed_status = (
                                "deferred_" + scope
                                if existing["status"].startswith("deferred_")
                                else existing["status"]
                            )
                            if old.get("scope") != scope:
                                c.execute(
                                    "UPDATE jobs SET payload=?,status=? WHERE dedup_key=?",
                                    (dumps(payload), changed_status, key),
                                )
                    candidates.append((key, payload))
        keys = {key for key, _ in candidates}
        for job in jobs:
            p = json.loads(job["payload"])
            if (
                p.get("planner") == PLANNER
                and job["dedup_key"] not in keys
                and job["status"]
                not in {
                    "succeeded",
                    "filtered_noise",
                    "superseded",
                    "running",
                    "excluded_source",
                }
            ):
                c.execute(
                    "UPDATE jobs SET status='superseded',error='input_replanned' WHERE id=?",
                    (job["id"],),
                )
        if retry:
            c.execute(
                "UPDATE jobs SET status='deferred_'||json_extract(payload,'$.scope'),attempts=0,error=NULL,available_at=? WHERE json_extract(payload,'$.planner')=? AND json_extract(payload,'$.conversation_id') IN (SELECT id FROM conversations WHERE account_id=? AND allowlisted=1 AND egress=1 AND followup_source=1) AND status IN ('blocked_credentials','blocked_budget','waiting_history_budget','failed','retry_wait')",
                (now(), PLANNER, account),
            )
    # Gate checks happen outside the write transaction (budget_state reads SQLite).
    if gate(db):
        return count
    budget = budget_state(db)
    if budget["remaining"] <= 0:
        from .crm import TZ

        until = (
            (datetime.now(TZ) + timedelta(days=1))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .isoformat()
        )
        hold(db, "blocked_budget", until)
        return count
    history_paused = gate(db, history=True) is not None
    with db.tx() as c:
        active = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE json_extract(payload,'$.planner')=? AND json_extract(payload,'$.conversation_id') IN (SELECT id FROM conversations WHERE account_id=? AND allowlisted=1 AND egress=1 AND followup_source=1) AND status IN ('queued','running','retry_wait')",
            (PLANNER, account),
        ).fetchone()[0]
        recent_pending = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE json_extract(payload,'$.planner')=? AND json_extract(payload,'$.scope')='recent' AND json_extract(payload,'$.conversation_id') IN (SELECT id FROM conversations WHERE account_id=? AND allowlisted=1 AND egress=1 AND followup_source=1) AND status NOT IN ('succeeded','filtered_noise','superseded')",
            (PLANNER, account),
        ).fetchone()[0]
        scope = "recent" if recent_pending else "history"
        room = max(0, BATCH - active) if scope == "recent" else max(0, 1 - active)
        # Leave 20% for new conversations, replies and on-demand drafts.
        if scope == "history" and (
            history_paused or budget["remaining"] <= budget["limit"] * 0.2
        ):
            room = 0
        if budget["remaining"] <= 0:
            room = 0
        for row in c.execute(
            "SELECT id FROM jobs WHERE status=? AND json_extract(payload,'$.planner')=? AND json_extract(payload,'$.conversation_id') IN (SELECT id FROM conversations WHERE account_id=? AND allowlisted=1 AND egress=1 AND followup_source=1) ORDER BY created_at,id LIMIT ?",
            ("deferred_" + scope, PLANNER, account, room),
        ).fetchall():
            c.execute("UPDATE jobs SET status='queued' WHERE id=?", (row["id"],))
    return count
