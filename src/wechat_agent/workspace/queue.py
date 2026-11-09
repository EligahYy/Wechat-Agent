"""Durable customer queue. Complete history per customer, serialized model work."""

import fcntl
import json
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ..analysis import Blocked, budget_state
from ..config import secret
from ..db import now
from .agent import run
from .context import snapshot
from .store import raw, stable
from .views import source_people


def settings(db):
    rows = db.rows(
        "SELECT * FROM workspace_automation WHERE account_id=?",
        (db.settings.source_account,),
    )
    return (
        rows[0]
        if rows
        else {"enabled": 0, "gate_error": None, "gate_until": None, "budget_stamp": ""}
    )


def configure(db, enabled):
    if not db.settings.source_account or type(enabled) is not bool:
        raise ValueError("workspace_invalid_automation")
    with db.tx() as c:
        c.execute(
            "INSERT INTO workspace_automation(account_id,enabled,updated_at) VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET enabled=excluded.enabled,gate_error=NULL,gate_until=NULL,updated_at=excluded.updated_at",
            (db.settings.source_account, int(enabled), now()),
        )
        db.event(
            c, db.settings.source_account, "workspace_automation", {"enabled": enabled}
        )
        if enabled:
            for row in c.execute(
                "SELECT source_id FROM workspace_queue WHERE account_id=? AND status='failed'",
                (db.settings.source_account,),
            ).fetchall():
                db.event(
                    c,
                    "workspace-retry:"
                    + stable(db.settings.source_account, row["source_id"]),
                    "workspace_retry",
                    {"source_id": row["source_id"]},
                )
            c.execute(
                "UPDATE workspace_queue SET status='queued',attempts=0,error=NULL,available_at=? WHERE account_id=? AND status IN ('paused','failed')",
                (now(), db.settings.source_account),
            )
    reconcile(db)
    return report(db)


def reconcile(db):
    """Index identities and changes locally; never call the model here."""
    account = db.settings.source_account
    if not account:
        return
    people = [p for p in source_people(db) if p["authorized"] and p["has_text"]]
    ids = {p["source_id"] for p in people}
    existing = {
        r["source_id"]: r
        for r in db.rows("SELECT * FROM workspace_queue WHERE account_id=?", (account,))
    }
    updates = []
    cutoff = datetime.now(UTC) - timedelta(days=15)
    for p in people:
        ident = p["source_id"]
        revision = snapshot(db, ident, False)
        previous = existing.get(ident)
        doc = raw(db, ident)
        done = bool(doc and json.loads(doc["body"]).get("source_revision") == revision)
        priority = 0 if datetime.fromisoformat(p["latest_event"]) >= cutoff else 1
        if (
            not previous
            or previous["input_revision"] != revision
            or previous["status"] == "excluded"
        ):
            updates.append(
                (
                    account,
                    ident,
                    revision,
                    "succeeded" if done else "queued",
                    priority,
                    now(),
                    now(),
                )
            )
        elif (
            done
            and previous["status"] != "succeeded"
            and previous["status"] != "running"
        ):
            updates.append(
                (account, ident, revision, "succeeded", priority, now(), now())
            )
    with db.tx() as c:
        for ident in set(existing) - ids:
            c.execute(
                "UPDATE workspace_queue SET status='excluded',error='source_excluded',updated_at=? WHERE account_id=? AND source_id=?",
                (now(), account, ident),
            )
        for update in updates:
            c.execute(
                "INSERT INTO workspace_queue(account_id,source_id,input_revision,status,priority,available_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET input_revision=excluded.input_revision,status=excluded.status,priority=excluded.priority,attempts=0,error=NULL,available_at=excluded.available_at,updated_at=excluded.updated_at",
                update,
            )


def retry(db, source_id):
    reconcile(db)
    with db.tx() as c:
        row = c.execute(
            "SELECT status FROM workspace_queue WHERE account_id=? AND source_id=?",
            (db.settings.source_account, source_id),
        ).fetchone()
        if not row or row["status"] == "excluded":
            raise ValueError("workspace_excluded_person")
        if row["status"] == "running":
            raise ValueError("workspace_already_running")
        db.event(
            c,
            "workspace-retry:" + stable(db.settings.source_account, source_id),
            "workspace_retry",
            {"source_id": source_id},
        )
        c.execute(
            "UPDATE workspace_queue SET status='queued',attempts=0,error=NULL,available_at=?,updated_at=? WHERE account_id=? AND source_id=?",
            (now(), now(), db.settings.source_account, source_id),
        )
    return report(db)


def report(db, page=1):
    if page < 1 or page > 100000:
        raise ValueError("workspace_invalid_query")
    state = settings(db)
    policy = db.rows(
        "SELECT enabled FROM crm_policies WHERE account_id=?",
        (db.settings.source_account,),
    )
    gate = (
        "awaiting_account"
        if not db.settings.source_account
        else "manual_mode"
        if db.settings.analysis_mode == "pilot"
        else "legacy_mode"
        if db.settings.analysis_mode == "legacy"
        else "paused"
        if not state["enabled"]
        else "blocked_policy"
        if not policy or not policy[0]["enabled"]
        else "blocked_credentials"
        if not secret("DEEPSEEK_API_KEY")
        else state.get("gate_error")
        if state.get("gate_until") is None or state["gate_until"] > now()
        else None
    )
    counts = {
        r["status"]: r["n"]
        for r in db.rows(
            "SELECT q.status,COUNT(*) n FROM workspace_queue q WHERE q.account_id=? AND q.status<>'excluded' AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=q.account_id AND e.source_id=q.source_id) GROUP BY q.status",
            (db.settings.source_account,),
        )
    }
    if (
        gate is None
        and counts.get("paused")
        and not counts.get("queued")
        and not counts.get("running")
    ):
        errors = db.rows(
            "SELECT DISTINCT error FROM workspace_queue WHERE account_id=? AND status='paused'",
            (db.settings.source_account,),
        )
        if errors and all(row["error"] == "blocked_budget" for row in errors):
            gate = "blocked_budget"
    rows = db.rows(
        "SELECT q.source_id,q.status,q.priority,q.attempts,q.error,q.available_at,q.updated_at,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),q.source_id) name FROM workspace_queue q LEFT JOIN identity_metadata i ON i.account_id=q.account_id AND i.source_id=q.source_id WHERE q.account_id=? AND q.status<>'excluded' AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=q.account_id AND e.source_id=q.source_id) ORDER BY CASE q.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1 WHEN 'queued' THEN 2 WHEN 'paused' THEN 3 ELSE 4 END,q.priority,q.available_at,q.source_id LIMIT 50 OFFSET ?",
        (db.settings.source_account, (page - 1) * 50),
    )
    return {
        "enabled": bool(state["enabled"]),
        "gate": gate,
        "counts": counts,
        "total": sum(counts.values()),
        "page": page,
        "has_more": sum(counts.values()) > page * 50,
        "items": rows,
    }


def _next_day():
    local = datetime.now(ZoneInfo("Asia/Shanghai"))
    return (
        (local + timedelta(days=1))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
        .isoformat()
    )


def step(db, refresh=True, client=None, stop=None):
    """One queue slice across processes; a person also has its own run lock."""
    fd = os.open(
        db.settings.data_dir / "workspace-queue.lock", os.O_CREAT | os.O_RDWR, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return _step(db, refresh, client, stop)
    finally:
        os.close(fd)


def _step(db, refresh, client, stop):
    if refresh:
        reconcile(db)
    account = db.settings.source_account
    state = settings(db)
    if not account or not state["enabled"] or db.settings.analysis_mode != "workspace":
        return False
    policy = db.rows("SELECT enabled FROM crm_policies WHERE account_id=?", (account,))
    if not policy or not policy[0]["enabled"] or not secret("DEEPSEEK_API_KEY"):
        return False
    budget = budget_state(db)
    # A new day or changed budget wakes budget-paused jobs, without clearing usage.
    stamp = stable(budget["day"], budget["limit"])
    with db.tx() as c:
        if state["budget_stamp"] != stamp:
            c.execute(
                "UPDATE workspace_queue SET available_at=? WHERE account_id=? AND status='paused' AND error='blocked_budget'",
                (now(), account),
            )
            c.execute(
                "UPDATE workspace_automation SET budget_stamp=? WHERE account_id=?",
                (stamp, account),
            )
        # The file lock proves no previous queue worker still owns these rows.
        c.execute(
            "UPDATE workspace_queue SET status='queued',available_at=? WHERE account_id=? AND status='running'",
            (now(), account),
        )
    if state.get("gate_error") and (
        state.get("gate_until") is None or state["gate_until"] > now()
    ):
        return False
    with db.tx() as c:
        row = c.execute(
            "SELECT * FROM workspace_queue WHERE account_id=? AND status IN ('queued','paused') AND available_at<=? ORDER BY priority,CASE WHEN status='paused' THEN 0 ELSE 1 END,available_at,source_id LIMIT 1",
            (account, now()),
        ).fetchone()
        if not row:
            return False
        item = dict(row)
        c.execute(
            "UPDATE workspace_queue SET status='running',updated_at=? WHERE account_id=? AND source_id=?",
            (now(), account, item["source_id"]),
        )

    def should_stop():
        return bool((stop and stop()) or not settings(db)["enabled"])

    status, error, attempts, available = "succeeded", None, 0, now()
    gate_error, gate_until = None, None
    try:
        result = run(db, item["source_id"], client, should_stop=should_stop)
        if result.get("paused"):
            status, error = "paused", result["reason"]
            available = (
                _next_day()
                if error == "blocked_budget"
                else (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
            )
        elif (
            snapshot(db, item["source_id"], False)
            != json.loads(raw(db, item["source_id"])["body"])["source_revision"]
        ):
            status = "queued"  # An append landed while the pinned history was read.
            available = (datetime.now(UTC) + timedelta(seconds=15)).isoformat()
    except (ValueError, Blocked) as exc:
        error = exc.status if isinstance(exc, Blocked) else str(exc)
        # Only codes from our agent/locks may appear in the queue UI.
        if not error.startswith(
            ("workspace_", "blocked_", "HTTP_", "Connect", "Proxy", "Read", "model_")
        ):
            error = "workspace_worker_error"
        attempts = item["attempts"] + 1
        if error in {"workspace_stale_input", "workspace_already_running"}:
            status, attempts = "queued", item["attempts"]
            available = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        elif error.startswith(("Connect", "Proxy", "Read")) or error in {
            "HTTP_429",
            "HTTP_500",
            "HTTP_502",
            "HTTP_503",
            "HTTP_504",
        }:
            status = "paused" if attempts < 3 else "failed"
            available = (
                datetime.now(UTC) + timedelta(minutes=5 * attempts)
            ).isoformat()
            gate_error, gate_until = error, available
        else:
            status = "failed"
            if error in {
                "HTTP_400",
                "HTTP_401",
                "HTTP_402",
                "HTTP_403",
                "HTTP_404",
                "blocked_credentials",
            } or error.startswith("model_"):
                gate_error = error
    with db.tx() as c:
        # A source exclusion or new desired revision wins over this old slice.
        c.execute(
            "UPDATE workspace_queue SET status=?,attempts=?,error=?,available_at=?,updated_at=? WHERE account_id=? AND source_id=? AND status='running' AND input_revision=?",
            (
                status,
                attempts,
                error,
                available,
                now(),
                account,
                item["source_id"],
                item["input_revision"],
            ),
        )
        if gate_error:
            c.execute(
                "UPDATE workspace_automation SET gate_error=?,gate_until=?,updated_at=? WHERE account_id=?",
                (gate_error, gate_until, now(), account),
            )
    return True
