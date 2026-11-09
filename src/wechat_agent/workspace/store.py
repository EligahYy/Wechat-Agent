"""One customer document; every update shares evidence and version checks."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..db import dumps, now, uid
from ..services import Conflict
from .order_links import linked_keys
from .quality import ENGINE_VERSION, display_text, validate_proposal
from .schema import Followup


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


def source_chats(db):
    """Local discovery scope; model authorization is checked separately."""
    return db.rows(
        "SELECT * FROM conversations v WHERE account_id=? AND allowlisted=1 AND followup_source=1 AND NOT EXISTS(SELECT 1 FROM actor_exclusions e WHERE e.account_id=v.account_id AND e.source_id=v.source_id AND v.kind='private')",
        (db.settings.source_account,),
    )


def allowed_chats(db):
    return [v for v in source_chats(db) if v["egress"]]


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
    allowed = [v["id"] for v in allowed_chats(db)]
    if not refs:
        return False
    count = db.rows(
        "SELECT COUNT(*) n FROM json_each(?) r JOIN messages m ON m.id=json_extract(r.value,'$.id') AND m.revision=json_extract(r.value,'$.revision') LEFT JOIN message_extractions x ON x.message_id=m.id AND x.source_revision=m.revision AND x.confirmed_text<>'' LEFT JOIN attachments a ON a.message_id=m.id WHERE (json_extract(r.value,'$.extraction_version') IS NULL OR (json_extract(r.value,'$.extraction_version')=x.version AND a.sha256=x.sha256)) AND m.conversation_id IN (SELECT value FROM json_each(?))",
        (dumps(refs), dumps(allowed)),
    )[0]["n"]
    return count == len(refs)


def reference(message):
    ref = {"id": message["id"], "revision": message["revision"]}
    if message.get("extraction_version"):
        ref["extraction_version"] = message["extraction_version"]
    return ref


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

    validate_proposal(proposal, context)
    with db.tx() as c:
        eligible(db, source_id)
        unchanged = (
            context["input_guard"]()
            if context.get("input_guard")
            else snapshot(db, source_id) == fingerprint
        )
        if not unchanged:
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
        body["history"] = prior_body.get("history", [])
        body["clue_resolutions"] = prior_body.get("clue_resolutions", {})
        body["batch_overrides"] = prior_body.get("batch_overrides", {})
        body["locks"] = prior_body.get("locks", {})
        body["locks"].update(
            {
                k: True
                for k, v in prior_body.get("actions", {}).items()
                if v.get("locked")
            }
        )
        if previous and not usable:
            # An unrelated chat edit must not erase still-valid human reviews.
            body["notes"].update(
                {
                    ident: item
                    for ident, item in prior_body.get("notes", {}).items()
                    if item.get("manual_verified") and valid_refs(db, item["evidence"])
                }
            )
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
            selected = [evidence[k] for k in linked_keys(keys, evidence)]
            if not any(m["anchor"] for m in selected):
                raise ValueError("workspace_customer_anchor_required")
            return [reference(m) for m in selected]

        refs(proposal.evidence)
        body["relationship"] = body.get("manual_role", proposal.relationship)
        # Reviewed notes replace prior machine drafts. User corrections survive.
        body["notes"] = {k: v for k, v in body["notes"].items() if v.get("text_locked")}
        for note in proposal.notes:
            if any(
                v["evidence"] == refs(note.evidence) and v.get("text_locked")
                for v in body["notes"].values()
            ):
                continue
            body["notes"][stable(note.text)] = {
                "text": note.text,
                "quality_warnings": context.get("field_warnings", {}).get(
                    note.text, []
                ),
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
                or (
                    old["stage"] == "fulfillment"
                    and item.stage not in {"fulfillment", "reported_shipped", "closed"}
                )
                or (old["stage"] == "reported_shipped" and item.stage != "closed")
            ):
                continue
            override = body["batch_overrides"].get(ident)
            if override:
                item.stage = override["stage"]
            elif old and old.get("stage_locked"):
                item.stage = old["stage"]
            body["batches"][ident] = {
                "text": old["text"] if old and old.get("text_locked") else item.text,
                "text_locked": bool(old and old.get("text_locked")),
                "stage": item.stage,
                "stage_locked": bool(override or (old and old.get("stage_locked"))),
                "manual_stage_note": override["note"]
                if override
                else old.get("manual_stage_note", "")
                if old
                else "",
                "quality_warnings": context.get("field_warnings", {}).get(
                    item.text, []
                ),
                "event_time": when,
                "evidence": evid,
            }
            new_batches[item.origin] = ident
        post_shipment_only = bool(body["batches"]) and all(
            b["stage"] in {"fulfillment", "reported_shipped", "closed"}
            for b in body["batches"].values()
        )
        updated_actions = set()
        for item in proposal.actions:
            if post_shipment_only:
                continue
            evid = refs(item.evidence)
            if item.origin not in item.evidence:
                raise ValueError("workspace_origin_required")
            batch = new_batches.get(item.batch, item.batch)
            if batch and batch not in body["batches"]:
                raise ValueError("workspace_unknown_batch")
            ident = item.ref or stable(
                "action", source_id, batch, item.kind, evidence[item.origin]["id"]
            )
            updated_actions.add(ident)
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
            if batch and body["batches"][batch]["stage"] in {
                "closed",
                "reported_shipped",
                "fulfillment",
            }:
                continue
            if item.due_date:
                date.fromisoformat(item.due_date)
            reasons = list(context.get("field_warnings", {}).get(item.text, []))
            action_state = item.state
            if item.state in {"open", "waiting"}:
                if not context["complete"]:
                    reasons.append("incomplete_context")
                if body["relationship"] != "merchant":
                    reasons.append("role_unconfirmed")
                if item.owner == "unknown":
                    reasons.append("owner_unclear")
                if item.owner in {"customer", "provider"}:
                    action_state = "waiting"
                if datetime.fromisoformat(when) < datetime.now(UTC) - timedelta(
                    days=30
                ) and (
                    not item.due_date
                    or item.due_date
                    < datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
                ):
                    reasons.append("historical_request")
                if reasons:
                    action_state = "proposed"
            body["actions"][ident] = {
                "text": old["text"] if old and old.get("text_locked") else item.text,
                "text_locked": bool(old and old.get("text_locked")),
                "reason": item.reason,
                "owner": item.owner,
                "review_reasons": reasons,
                "batch": batch,
                "kind": item.kind,
                "state": action_state,
                "due_date": item.due_date,
                "event_time": when,
                "evidence": evid,
            }
        for aid, action in body["actions"].items():
            if (
                aid not in updated_actions
                and not action.get("locked")
                and action["state"] in {"open", "waiting", "proposed"}
            ):
                action.update(state="proposed", review_reasons=["not_revalidated"])

            if (
                action.get("batch")
                and body["batches"][action["batch"]]["stage"]
                in {"closed", "reported_shipped", "fulfillment"}
                and action["state"] in {"open", "waiting", "proposed"}
            ):
                action["state"] = "cancelled"
        body["decisions"] = {
            k: v
            for k, v in body["decisions"].items()
            if k == "role" or v.get("resolved")
        }
        for item in proposal.decisions:
            if post_shipment_only and (
                item.key != "role" or body["relationship"] == "merchant"
            ):
                continue
            if item.key != "role" and (
                not item.blocks_followup or not item.impact.strip()
            ):
                continue
            batch = new_batches.get(item.batch, item.batch)
            if batch and batch not in body["batches"]:
                raise ValueError("workspace_unknown_batch")
            if batch and body["batches"][batch]["stage"] in {
                "fulfillment",
                "reported_shipped",
                "closed",
            }:
                continue
            decision_id = (
                "role"
                if item.key == "role"
                else stable("decision", item.key, batch or "customer")
            )
            if body["decisions"].get(decision_id, {}).get("resolved"):
                continue
            body["decisions"][decision_id] = {
                "key": item.key,
                "batch": batch,
                "text": item.text,
                "impact": item.impact,
                "evidence": refs(item.evidence),
                "resolved": False,
            }
        if body["relationship"] == "candidate" and not body["decisions"].get(
            "role", {}
        ).get("resolved"):
            body["decisions"].setdefault(
                "role",
                {
                    "text": "此联系人是否为需要跟进的商家？",
                    "evidence": refs(proposal.evidence),
                    "resolved": False,
                },
            )
        body["unattributed"] = [
            {
                "section": entry["section"],
                "code": entry["code"],
                "text": entry["item"]["text"],
                "evidence": [
                    reference(evidence[k])
                    for k in entry["item"]["evidence"]
                    if k in evidence
                ],
            }
            for entry in context.get("unattributed", [])
        ]
        from .clues import pending, sync_issues

        body["unattributed"] = pending(body)
        sync_issues(body)

        if post_shipment_only:
            for action in body["actions"].values():
                if action["state"] in {
                    "open",
                    "waiting",
                    "proposed",
                    "historical_unresolved",
                }:
                    action["state"] = "cancelled"
            body["decisions"] = {
                k: v
                for k, v in body["decisions"].items()
                if v.get("resolved")
                or (k == "role" and body["relationship"] != "merchant")
            }
        body["engine_version"] = ENGINE_VERSION
        body["source_revision"] = context.get("source_revision") or snapshot(
            db, source_id, False
        )
        body["coverage"] = {
            "complete_context": context["complete"],
            "messages": len(evidence),
            "gaps": context.get("gaps", []),
            "source_messages": context.get("source_messages", len(evidence)),
            "value_filtered": 0,
            "pages": context.get("pages", 0),
            "processed_messages": context.get("processed_messages", len(evidence)),
        }
        read_set = (
            {r["id"]: r for r in json.loads(previous["read_set"])} if usable else {}
        )
        read_set.update({m["id"]: reference(m) for m in evidence.values()})
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
        elif operation == "resolve_clue":
            from .clues import resolve

            resolve(db, body, target, value)
        elif operation == "restore_clue":
            from .clues import restore

            restore(db, body, target)
        elif operation == "followup":
            entry = Followup.model_validate(value)
            if not entry.note.strip():
                raise ValueError("workspace_followup_note_required")
            entry.note = entry.note.strip()
            if entry.next_date:
                try:
                    when = date.fromisoformat(entry.next_date)
                except ValueError:
                    raise ValueError("workspace_invalid_date") from None
                if (
                    when.isoformat() != entry.next_date
                    or when < datetime.now(ZoneInfo("Asia/Shanghai")).date()
                ):
                    raise ValueError("workspace_invalid_date")
            if entry.action_id:
                if entry.action_id not in body["actions"]:
                    raise ValueError("workspace_unknown_action")
                action = body["actions"][entry.action_id]
                if entry.action_state == "waiting" and action["state"] in {
                    "proposed",
                    "historical_unresolved",
                }:
                    raise ValueError("workspace_confirmation_required")
                if entry.action_state != "keep":
                    if (
                        entry.action_state == "waiting"
                        and action.get("batch")
                        and body["batches"][action["batch"]]["stage"]
                        in {"fulfillment", "reported_shipped", "closed"}
                    ):
                        raise ValueError("workspace_closed_batch")
                    action.update(state=entry.action_state, locked=True)
                    if entry.action_state == "done":
                        action["completed_at"] = now()
                if entry.next_date:
                    action["due_date"] = entry.next_date
                    action["locked"] = True
            elif entry.action_state != "keep" or entry.next_date:
                raise ValueError("workspace_action_required")
            db.event(c, document["id"], "workspace_followup", entry.model_dump())
            body["source_revision"] = None
        elif (
            operation == "batch_stage"
            and target in body["batches"]
            and isinstance(value, dict)
        ):
            stage = value.get("stage")
            if stage not in {
                "needs",
                "quoting",
                "decision",
                "preparing",
                "fulfillment",
                "reported_shipped",
                "closed",
                "auto",
            }:
                raise ValueError("workspace_invalid_stage")
            batch = body["batches"][target]
            if stage == "auto":
                batch["stage_locked"] = False
                batch["manual_stage_note"] = ""
                body.setdefault("batch_overrides", {}).pop(target, None)
            else:
                note = value.get("note")
                if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
                    raise ValueError("workspace_stage_note_required")
                batch.update(
                    stage=stage, stage_locked=True, manual_stage_note=note.strip()
                )
                body.setdefault("batch_overrides", {})[target] = {
                    "stage": stage,
                    "note": note.strip(),
                }
                if stage in {"fulfillment", "reported_shipped", "closed"}:
                    for action in body["actions"].values():
                        if action.get("batch") == target and action["state"] in {
                            "open",
                            "waiting",
                            "proposed",
                        }:
                            action["state"] = "cancelled"
            body["source_revision"] = None
        elif (
            operation == "correct"
            and isinstance(value, str)
            and 0 < len(value.strip()) <= 500
        ):
            section, _, ident = (target or "").partition(":")
            if (
                section not in {"notes", "batches", "actions"}
                or ident not in body[section]
            ):
                raise ValueError("workspace_invalid_correction")
            body[section][ident].update(
                text=display_text(value.strip()), text_locked=True
            )
            body["source_revision"] = None
        elif operation in {"schedule", "confirm_action"} and target in body["actions"]:
            item = body["actions"][target]
            if item.get("batch") and body["batches"][item["batch"]]["stage"] in {
                "closed",
                "reported_shipped",
                "fulfillment",
            }:
                raise ValueError("workspace_closed_batch")
            if body["relationship"] != "merchant":
                raise ValueError("workspace_role_required")
            if operation == "schedule":
                if item["state"] not in {"open", "waiting"} or not isinstance(
                    value, str
                ):
                    raise ValueError("workspace_action_not_active")
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    raise ValueError("workspace_invalid_date") from None
                if (
                    parsed < datetime.now(ZoneInfo("Asia/Shanghai")).date()
                    or parsed.isoformat() != value
                ):
                    raise ValueError("workspace_invalid_date")
                item.update(due_date=value, state="open", locked=True, confirmed=True)
            else:
                if value is not True or item["state"] not in {
                    "proposed",
                    "historical_unresolved",
                }:
                    raise ValueError("workspace_invalid_command")
                item.update(
                    state="open",
                    owner="platform",
                    confirmed=True,
                    locked=True,
                    review_reasons=[],
                )
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
                in {"closed", "reported_shipped", "fulfillment"}
            ):
                raise ValueError("workspace_closed_batch")
            if value in {"open", "waiting"} and item["state"] in {
                "proposed",
                "historical_unresolved",
            }:
                raise ValueError("workspace_confirmation_required")
            item.update(state=value, locked=True)
            item["completed_at"] = now() if value == "done" else None
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
        body["history"] = (
            body.get("history", [])
            + [{"at": now(), "operation": operation, "target": target, "value": value}]
        )[-50:]
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
