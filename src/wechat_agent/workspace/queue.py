"""Durable customer queue. Complete history per customer, serialized model work."""

import fcntl
import json
import os
from datetime import UTC, datetime, timedelta

from ..analysis import Blocked
from ..config import secret
from ..db import now
from .agent import run
from .context import snapshot
from .control import command_lock, running
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
                "SELECT source_id FROM workspace_queue WHERE account_id=? AND status='failed' AND user_paused=0",
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
                "UPDATE workspace_queue SET status='queued',attempts=0,error=NULL,available_at=?,updated_at=? WHERE account_id=? AND status IN ('paused','failed') AND user_paused=0",
                (now(), now(), db.settings.source_account),
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
        elif not done and previous["status"] == "succeeded":
            # Manual feedback can invalidate the document without changing chats.
            updates.append((account, ident, revision, "queued", priority, now(), now()))
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
                "INSERT INTO workspace_queue(account_id,source_id,input_revision,status,priority,available_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET input_revision=excluded.input_revision,status=CASE WHEN workspace_queue.user_paused=1 AND excluded.status<>'succeeded' THEN 'paused' ELSE excluded.status END,priority=excluded.priority,attempts=0,error=CASE WHEN workspace_queue.user_paused=1 AND excluded.status<>'succeeded' THEN 'customer_paused' ELSE NULL END,available_at=excluded.available_at,updated_at=excluded.updated_at",
                update,
            )


def _transition(db, source_id, action, *, reconciled=False):
    """Single durable transition for user commands; callers decide execution."""
    if action not in {"start", "pause", "resume", "retry"}:
        raise ValueError("workspace_invalid_control")
    if not reconciled:
        reconcile(db)
    with db.tx() as c:
        row = c.execute(
            "SELECT status,user_paused FROM workspace_queue WHERE account_id=? AND source_id=?",
            (db.settings.source_account, source_id),
        ).fetchone()
        if not row or row["status"] == "excluded":
            raise ValueError("workspace_excluded_person")
        if action == "retry" or action != "pause" and row["status"] == "failed":
            db.event(
                c,
                "workspace-retry:" + stable(db.settings.source_account, source_id),
                "workspace_retry",
                {"source_id": source_id},
            )
        c.execute(
            "UPDATE workspace_queue SET user_paused=?,control_version=control_version+1,status=?,priority=-1,attempts=0,error=?,available_at=?,updated_at=? WHERE account_id=? AND source_id=?",
            (
                int(action == "pause"),
                "paused" if action == "pause" else "queued",
                "customer_paused" if action == "pause" else None,
                now(),
                now(),
                db.settings.source_account,
                source_id,
            ),
        )


def _scheduler(db, background):
    state = settings(db)
    policy = db.rows(
        "SELECT enabled FROM crm_policies WHERE account_id=?",
        (db.settings.source_account,),
    )
    gate = (
        "awaiting_account"
        if not db.settings.source_account
        else "blocked_policy"
        if not policy or not policy[0]["enabled"]
        else "blocked_credentials"
        if not secret("DEEPSEEK_API_KEY")
        else "legacy_mode"
        if db.settings.analysis_mode == "legacy"
        else "manual_mode"
        if db.settings.analysis_mode == "pilot"
        else "no_background"
        if not background
        else "paused"
        if not state["enabled"]
        else state.get("gate_error")
        if state.get("gate_until") is None or state["gate_until"] > now()
        else None
    )
    return {
        "enabled": bool(state["enabled"]),
        "gate": gate,
        "background": bool(background),
    }


def _starting(job):
    return bool(
        job
        and job["status"] == "running"
        and 0
        <= (
            datetime.now(UTC) - datetime.fromisoformat(job["updated_at"])
        ).total_seconds()
        < 15
    )


def _jobs(db, background=True):
    """One projection shared by summary, list, actions and command responses."""
    scheduler = _scheduler(db, background)
    people = {
        p["source_id"]: p
        for p in source_people(db)
        if p["authorized"] and p["has_text"]
    }
    account = db.settings.source_account
    scans = {
        s["source_id"]: s
        for s in db.rows("SELECT * FROM workspace_scans WHERE account_id=?", (account,))
    }
    queued = {
        q["source_id"]: q
        for q in db.rows("SELECT * FROM workspace_queue WHERE account_id=?", (account,))
    }
    items = []
    for ident in (set(scans) | set(queued)) & set(people):
        scan, job = scans.get(ident), queued.get(ident)
        if job and job["status"] == "excluded":
            continue
        latest = max([r for r in (scan, job) if r], key=lambda r: r["updated_at"])
        active = running(db, ident)
        paused = bool(job and job["user_paused"])
        starting = _starting(job)
        record = job or scan
        completed = record["status"] == "succeeded"
        status = (
            "stopping"
            if active and paused
            else "running"
            if active
            else "starting"
            if starting and not paused
            else "succeeded"
            if completed
            else "paused"
            if paused
            else "failed"
            if record["status"] == "failed"
            else "paused"
            if record["status"] == "paused"
            else "queued"
            if scheduler["gate"] is None
            else "ready"
        )
        started = bool(scan and (scan["source_messages"] or scan["total_pages"]))
        action = (
            None
            if status in {"succeeded", "stopping", "starting"}
            else {"action": "pause", "label": "暂停分析"}
            if status == "running"
            else {"action": "retry", "label": "重试分析"}
            if status == "failed"
            else {"action": "resume", "label": "继续分析"}
            if started or paused or status == "paused"
            else {"action": "start", "label": "开始分析"}
        )
        if action:
            action["disabled"] = action["action"] != "pause" and scheduler["gate"] in {
                "awaiting_account",
                "blocked_policy",
                "blocked_credentials",
                "legacy_mode",
            }
        item = {
            "source_id": ident,
            "name": people[ident]["name"],
            "status": status,
            "status_label": {
                "ready": "等待分析",
                "queued": "排队中",
                "starting": "正在启动",
                "running": "正在整理",
                "stopping": "正在暂停",
                "failed": "需要处理",
                "succeeded": "已完成",
                "paused": "已暂停" if paused else "等待续跑",
            }[status],
            "pending_label": {"starting": "正在启动…", "stopping": "正在暂停…"}.get(
                status
            ),
            "phase": scan["phase"] if scan else "queued",
            "error": "customer_paused" if paused else latest["error"],
            "user_paused": paused,
            "updated_at": latest["updated_at"],
            "primary_action": action,
            "priority": job["priority"] if job else 0,
            "attempts": job["attempts"] if job else 0,
        }
        for key in (
            "total_pages",
            "completed_pages",
            "source_messages",
            "processed_messages",
        ):
            item[key] = scan[key] if scan else 0
        items.append(item)
    items.sort(key=lambda i: (i["updated_at"], i["source_id"]), reverse=True)
    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return items, scheduler | {"counts": counts, "total": len(items)}


def progress(db, page=1, background=True):
    if not 1 <= page <= 100000:
        raise ValueError("workspace_invalid_query")
    jobs, summary = _jobs(db, background)
    items = [item for item in jobs if item["status"] != "succeeded"]
    total = len(items)
    pages = max(1, (total + 19) // 20)
    page = min(page, pages)
    return {
        "items": items[(page - 1) * 20 : page * 20],
        "page": page,
        "page_size": 20,
        "total": total,
        "pages": pages,
        "has_more": page < pages,
        "summary": summary,
    }


def report(db, page=1, background=True):
    if not 1 <= page <= 100000:
        raise ValueError("workspace_invalid_query")
    items, summary = _jobs(db, background)
    return summary | {
        "items": items[(page - 1) * 50 : page * 50],
        "page": page,
        "has_more": len(items) > page * 50,
    }


def command(db, source_id, action, *, background=True, client=None):
    """All UI/CLI start, resume, retry and pause paths enter here once."""
    if not isinstance(source_id, str) or not 0 < len(source_id) <= 200:
        raise ValueError("workspace_invalid_identity")
    if not isinstance(action, str) or action not in {
        "start",
        "resume",
        "retry",
        "pause",
    }:
        raise ValueError("workspace_invalid_control")
    with command_lock(db, source_id):
        item, result = _prepare_command(db, source_id, action, background)
    if item is None:
        return result
    result, error = _perform(db, item, client, None)
    jobs, _ = _jobs(db, background)
    current = next((job for job in jobs if job["source_id"] == source_id), None)
    execution = current["status"] if current else "excluded"
    if error and not (current and current["user_paused"]):
        raise ValueError(error)
    return result | {
        "source_id": source_id,
        "execution": "completed" if execution == "succeeded" else execution,
        "paused": execution in {"paused", "stopping"},
    }


def _prepare_command(db, source_id, action, background):
    reconcile(db)
    jobs, scheduler = _jobs(db, background)
    current = next((i for i in jobs if i["source_id"] == source_id), None)
    if current is None:
        raise ValueError("workspace_excluded_person")
    if action == "pause":
        if current["status"] == "running":
            _transition(db, source_id, action, reconciled=True)
        return None, {
            "source_id": source_id,
            "execution": "stopping"
            if current["status"] == "running"
            else current["status"],
            "paused": current["status"] in {"running", "stopping", "paused"},
        }
    if current["status"] == "stopping":
        raise Blocked("workspace_pause_pending")
    if current["status"] in {"running", "starting"}:
        return None, {"source_id": source_id, "execution": current["status"]}
    if scheduler["gate"] in {
        "awaiting_account",
        "blocked_policy",
        "blocked_credentials",
        "legacy_mode",
    }:
        raise Blocked(scheduler["gate"])
    if current["status"] == "succeeded":
        doc = raw(db, source_id)
        if doc:
            if current["user_paused"]:
                _transition(db, source_id, action, reconciled=True)
                reconcile(db)
            return None, {
                "source_id": source_id,
                "execution": "completed",
                "cached": True,
                "customer_id": doc["id"],
                "version": doc["version"],
            }
    _transition(db, source_id, action, reconciled=True)
    if scheduler["gate"] is None:
        return None, {"source_id": source_id, "execution": "queued"}
    # Automatic scheduling off: execute this explicitly requested customer only.
    item = _claim(db, source_id)
    return (
        (item, None)
        if item
        else (None, {"source_id": source_id, "execution": "running"})
    )


def _claim(db, source_id):
    """Called under the customer command lock by both execution paths."""
    with db.tx() as c:
        row = c.execute(
            "SELECT * FROM workspace_queue WHERE account_id=? AND source_id=? AND user_paused=0 AND status IN ('queued','paused') AND available_at<=?",
            (db.settings.source_account, source_id, now()),
        ).fetchone()
        if not row or running(db, source_id):
            return None
        c.execute(
            "UPDATE workspace_queue SET status='running',updated_at=? WHERE account_id=? AND source_id=?",
            (now(), db.settings.source_account, source_id),
        )
    return dict(row)


def retry(db, source_id):
    return command(db, source_id, "retry")


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
    # A manual command may own the customer even when this queue lock is free.
    # Recover only abandoned claims, allowing a short claim-to-lock handoff.
    for row in db.rows(
        "SELECT * FROM workspace_queue WHERE account_id=? AND status='running' AND user_paused=0",
        (account,),
    ):
        if not running(db, row["source_id"]) and not _starting(row):
            with db.tx() as c:
                c.execute(
                    "UPDATE workspace_queue SET status='queued',available_at=?,updated_at=? WHERE account_id=? AND source_id=? AND status='running' AND control_version=?",
                    (now(), now(), account, row["source_id"], row["control_version"]),
                )
    if state.get("gate_error") and (
        state.get("gate_until") is None or state["gate_until"] > now()
    ):
        return False
    candidates = db.rows(
        "SELECT source_id FROM workspace_queue WHERE account_id=? AND user_paused=0 AND status IN ('queued','paused') AND available_at<=? ORDER BY priority,CASE WHEN status='paused' THEN 0 ELSE 1 END,available_at,source_id",
        (account, now()),
    )
    item = None
    for candidate in candidates:
        with command_lock(db, candidate["source_id"]):
            item = _claim(db, candidate["source_id"])
        if item:
            break
    if not item:
        return False

    _perform(
        db, item, client, lambda: bool((stop and stop()) or not settings(db)["enabled"])
    )
    return True


def _perform(db, item, client, should_stop):
    """The same claim/run/settle logic for automatic and explicit execution."""
    account = db.settings.source_account
    result, caught = {}, None
    status, error, attempts, available = "succeeded", None, 0, now()
    gate_error, gate_until = None, None
    try:
        result = run(db, item["source_id"], client, should_stop=should_stop)
        if result.get("paused"):
            status, error = "paused", result["reason"]
            available = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
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
        caught = error
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
        updated = c.execute(
            "UPDATE workspace_queue SET status=?,attempts=?,error=?,available_at=?,updated_at=? WHERE account_id=? AND source_id=? AND status='running' AND input_revision=? AND control_version=? AND user_paused=0",
            (
                status,
                attempts,
                error,
                available,
                now(),
                account,
                item["source_id"],
                item["input_revision"],
                item["control_version"],
            ),
        )
        if gate_error and updated.rowcount:
            c.execute(
                "UPDATE workspace_automation SET gate_error=?,gate_until=?,updated_at=? WHERE account_id=?",
                (gate_error, gate_until, now(), account),
            )
    return result, caught
