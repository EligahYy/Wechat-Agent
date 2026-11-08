"""One customer document; every update shares evidence and version checks."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from ..db import dumps, now, uid
from ..services import Conflict


def stable(*parts):
    return hashlib.sha256(dumps(parts).encode()).hexdigest()[:32]


def eligible(db, source_id):
    account = db.settings.source_account
    if (
        not account
        or not isinstance(source_id, str)
        or not source_id
        or source_id in {"unknown", account}
        or source_id.endswith("@chatroom")
    ):
        raise ValueError("workspace_invalid_identity")
    if db.rows(
        "SELECT 1 FROM actor_exclusions WHERE account_id=? AND source_id=?",
        (account, source_id),
    ):
        raise ValueError("workspace_excluded_person")


def allowed_chats(db):
    return db.rows(
        "SELECT * FROM conversations v WHERE account_id=? AND allowlisted=1 AND egress=1 AND followup_source=1 AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=v.account_id AND e.source_id=v.source_id AND v.kind='private')",
        (db.settings.source_account,),
    )


def legacy_paused(db, source_id):
    # Preserve an existing do-not-contact preference, not old AI facts/tasks.
    return bool(
        db.rows(
            "SELECT 1 FROM crm_customers c JOIN crm_contacts n ON n.id=c.contact_id WHERE c.account_id=? AND n.source_id=? AND c.do_not_contact=1",
            (db.settings.source_account, source_id),
        )
    )


def raw(db, source_id):
    rows = db.rows(
        "SELECT * FROM workspace_documents WHERE account_id=? AND source_id=?",
        (db.settings.source_account, source_id),
    )
    return rows[0] if rows else None


def valid_refs(db, refs):
    allowed = {v["id"] for v in allowed_chats(db)}
    return bool(refs) and all(
        db.rows(
            "SELECT 1 FROM messages WHERE id=? AND revision=? AND conversation_id IN (SELECT value FROM json_each(?))",
            (r["id"], r["revision"], dumps(list(allowed))),
        )
        for r in refs
    )


def read(db, source_id):
    eligible(db, source_id)
    row = raw(db, source_id)
    if not row:
        return None
    if not valid_refs(db, json.loads(row["read_set"])):
        raise ValueError("workspace_stale_evidence")
    return {"id": row["id"], "version": row["version"], "body": json.loads(row["body"])}


def save(c, db, source_id, body, refs, version, reason):
    ident = stable(db.settings.source_account, source_id)
    c.execute(
        "INSERT INTO workspace_documents VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET version=excluded.version,body=excluded.body,read_set=excluded.read_set,updated_at=excluded.updated_at",
        (
            ident,
            db.settings.source_account,
            source_id,
            version,
            dumps(body),
            dumps(refs),
            now(),
        ),
    )
    c.execute(
        "INSERT INTO workspace_versions VALUES(?,?,?,?,?,?)",
        (uid(), ident, version, dumps(body), reason, now()),
    )
    return {"id": ident, "version": version, "body": body}


def commit(db, source_id, proposal, context, fingerprint):
    from .context import snapshot

    with db.tx() as c:
        eligible(db, source_id)
        if snapshot(db, source_id) != fingerprint:
            raise Conflict("workspace_stale_input")
        previous = raw(db, source_id)
        usable = previous and valid_refs(db, json.loads(previous["read_set"]))
        body = (
            json.loads(previous["body"])
            if usable
            else {
                "relationship": "candidate",
                "notes": {},
                "batches": {},
                "actions": {},
                "decisions": {},
                "paused": False,
            }
        )
        prior_body = json.loads(previous["body"]) if previous else {}
        body["locks"] = prior_body.get("locks", {})
        body["locks"].update(
            {
                k: True
                for k, v in prior_body.get("actions", {}).items()
                if v.get("locked")
            }
        )
        if previous and not usable:
            body["paused"] = prior_body.get("paused", False)
            body["pause_override"] = prior_body.get("pause_override", False)
            if "manual_role" in prior_body:
                body["manual_role"] = prior_body["manual_role"]
            body["decisions"] = {
                k: {
                    "text": "已保存人工判断",
                    "resolved": True,
                    "resolution": v["resolution"],
                    "evidence": [],
                }
                for k, v in prior_body.get("decisions", {}).items()
                if v.get("resolved")
            }
        if not body.get("pause_override"):
            body["paused"] = legacy_paused(db, source_id)
        evidence = context["evidence"]

        def refs(keys):
            if not keys or any(k not in evidence for k in keys):
                raise ValueError("workspace_unknown_evidence")
            selected = [evidence[k] for k in set(keys)]
            if not any(m["anchor"] for m in selected):
                raise ValueError("workspace_customer_anchor_required")
            return [{"id": m["id"], "revision": m["revision"]} for m in selected]

        refs(proposal.evidence)
        body["relationship"] = body.get("manual_role", proposal.relationship)
        for note in proposal.notes:
            body["notes"][stable(note.text)] = {
                "text": note.text,
                "evidence": refs(note.evidence),
            }
        new_batches = {}
        for item in proposal.batches:
            if item.origin not in item.evidence:
                raise ValueError("workspace_origin_required")
            evid = refs(item.evidence)
            ident = item.ref or stable("batch", source_id, evidence[item.origin]["id"])
            old = body["batches"].get(ident)
            if item.ref and not old:
                raise ValueError("workspace_unknown_batch")
            new_batches[item.origin] = ident
            when = max(evidence[k]["event_time"] for k in item.evidence)
            if old and (
                old["event_time"] > when
                or old["stage"] == "closed"
                or (old["stage"] == "reported_shipped" and item.stage != "closed")
            ):
                continue
            body["batches"][ident] = {
                "text": item.text,
                "stage": item.stage,
                "event_time": when,
                "evidence": evid,
            }
            new_batches[item.origin] = ident
        for item in proposal.actions:
            evid = refs(item.evidence)
            if item.origin not in item.evidence:
                raise ValueError("workspace_origin_required")
            batch = new_batches.get(item.batch, item.batch)
            if batch and batch not in body["batches"]:
                raise ValueError("workspace_unknown_batch")
            ident = item.ref or stable(
                "action", source_id, batch, item.kind, evidence[item.origin]["id"]
            )
            old = body["actions"].get(ident)
            if body["locks"].get(ident):
                continue
            if item.ref and not old:
                raise ValueError("workspace_unknown_action")
            if old and old.get("batch") != batch:
                raise ValueError("workspace_action_batch_conflict")
            when = max(evidence[k]["event_time"] for k in item.evidence)
            if old and (old.get("locked") or old["event_time"] > when):
                continue
            if item.state in {"open", "waiting"} and (
                not context["complete"]
                or body["relationship"] != "merchant"
                or (
                    batch
                    and body["batches"][batch]["stage"]
                    in {"closed", "reported_shipped"}
                )
            ):
                continue
            if item.due_date:
                date.fromisoformat(item.due_date)
            action_state = item.state
            if (
                action_state in {"open", "waiting"}
                and datetime.fromisoformat(when)
                < datetime.now(UTC) - timedelta(days=30)
                and (
                    not item.due_date
                    or item.due_date < datetime.now(UTC).date().isoformat()
                )
            ):
                action_state = "historical_unresolved"
            body["actions"][ident] = {
                "text": item.text,
                "reason": item.reason,
                "batch": batch,
                "kind": item.kind,
                "state": action_state,
                "due_date": item.due_date,
                "event_time": when,
                "evidence": evid,
            }
        for action in body["actions"].values():
            if (
                action.get("batch")
                and body["batches"][action["batch"]]["stage"]
                in {"closed", "reported_shipped"}
                and action["state"] in {"open", "waiting"}
            ):
                action["state"] = "cancelled"
        for item in proposal.decisions:
            if body["decisions"].get(item.key, {}).get("resolved"):
                continue
            body["decisions"][item.key] = {
                "text": item.text,
                "evidence": refs(item.evidence),
                "resolved": False,
            }
        body["source_revision"] = snapshot(db, source_id, False)
        body["coverage"] = {
            "complete_context": context["complete"],
            "messages": len(evidence),
        }
        read_set = (
            {r["id"]: r for r in json.loads(previous["read_set"])} if usable else {}
        )
        read_set.update(
            {
                m["id"]: {"id": m["id"], "revision": m["revision"]}
                for m in evidence.values()
            }
        )
        return save(
            c,
            db,
            source_id,
            body,
            list(read_set.values()),
            previous["version"] + 1 if previous else 1,
            "agent",
        )


def command(db, source_id, expected_version, operation, target=None, value=None):
    if not isinstance(operation, str) or (
        target is not None and not isinstance(target, str)
    ):
        raise ValueError("workspace_invalid_command")
    if type(expected_version) is not int:
        raise ValueError("workspace_version_required")
    with db.tx() as c:
        document = read(db, source_id)
        if not document or document["version"] != expected_version:
            raise Conflict("workspace_version_conflict")
        body = document["body"]
        if operation == "pause" and type(value) is bool:
            body["paused"] = value
            body["pause_override"] = True
        elif (
            operation == "action"
            and target in body["actions"]
            and value in {"done", "cancelled", "open", "waiting"}
        ):
            item = body["actions"][target]
            if (
                value in {"open", "waiting"}
                and item.get("batch")
                and body["batches"][item["batch"]]["stage"]
                in {"closed", "reported_shipped"}
            ):
                raise ValueError("workspace_closed_batch")
            item.update(state=value, locked=True)
        elif (
            operation == "decision"
            and target in body["decisions"]
            and isinstance(value, str)
            and 0 < len(value.strip()) <= 500
        ):
            if target == "role":
                if value not in {"merchant", "non_target", "candidate"}:
                    raise ValueError("workspace_invalid_role")
                body["relationship"] = body["manual_role"] = value
            body["decisions"][target].update(resolved=True, resolution=value.strip())
        else:
            raise ValueError("workspace_invalid_command")
        if operation == "decision":
            body["source_revision"] = None
            if target == "role" and value == "candidate":
                body["decisions"][target]["resolved"] = False
                body.pop("manual_role", None)
        row = raw(db, source_id)
        return save(
            c,
            db,
            source_id,
            body,
            json.loads(row["read_set"]),
            expected_version + 1,
            "user:" + operation,
        )
