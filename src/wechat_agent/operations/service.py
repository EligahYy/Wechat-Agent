"""Durable intentions and guarded control; no source requests in HTTP creation."""

from datetime import datetime, timezone
import json
from uuid import uuid4

from pydantic import ValidationError

from .contracts import Operation, OperationItem, OperationScope, SyncOptions
from ..source.repository import transaction


class OperationError(Exception):
    def __init__(self, code, status=409, details=None):
        self.code, self.status, self.details = code, status, details or {}
        super().__init__(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def initial_counts():
    return {name: 0 for name in ("inserted", "revised", "unchanged", "pages_processed", "conversations_total",
        "completed_conversations", "failed_conversations", "incomplete_conversations", "analysis_required", "analysis_completed")}


def get_operation(conn, account_id, operation_id, *, include_items=True):
    row = conn.execute("SELECT * FROM operations WHERE account_id=? AND id=?", (account_id, operation_id)).fetchone()
    if row is None:
        raise OperationError("operation_not_found", 404)
    try:
        options = SyncOptions.model_validate_json(row["request_json"])
    except ValidationError:
        options = None
    source = conn.execute("SELECT state FROM operation_items WHERE account_id=? AND operation_id=? AND item_id='source'",
                          (account_id, operation_id)).fetchone()
    items = []
    if include_items:
        for item in conn.execute("SELECT * FROM operation_items WHERE account_id=? AND operation_id=? ORDER BY phase DESC,item_id",
                                 (account_id, operation_id)):
            items.append(OperationItem(id=item["item_id"], contact_id=item["contact_id"], conversation_id=item["conversation_id"],
                state=item["state"], phase=item["phase"], generation=item["generation"], counts=json.loads(item["counts_json"]),
                gaps=json.loads(item["gaps_json"]), error_code=item["error_code"], role_version=item["role_version"]))
    return Operation(id=row["id"], scope=OperationScope(account_id=account_id, contact_id=row["contact_id"]),
        action=row["action"], state=row["state"], phase=row["phase"], generation=row["generation"], remaining=row["remaining"],
        counts=json.loads(row["counts_json"]), error_code=row["error_code"], source_state=source[0] if source else None,
        items=items, options=options, created_at=row["created_at"], updated_at=row["updated_at"])


def create_operation(conn, action, scope, idempotency_key, *, options=None):
    if action not in {"sync", "sync_and_organize"}:
        raise OperationError("unsupported_action", 422)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key)>256:
        raise OperationError("invalid_idempotency_key", 422)
    scope = OperationScope.model_validate(scope.model_dump())
    options = SyncOptions.model_validate(options.model_dump() if options else {})
    encoded = json.dumps(options.model_dump(), sort_keys=True)
    with transaction(conn):
        old = conn.execute("SELECT * FROM operations WHERE account_id=? AND idempotency_key=?",
                           (scope.account_id, idempotency_key)).fetchone()
        if old:
            if old["action"] != action or old["contact_id"] != scope.contact_id or old["request_json"] != encoded:
                raise OperationError("idempotency_key_conflict")
            operation_id = old["id"]
        else:
            active = conn.execute("""SELECT id FROM operations WHERE account_id=? AND contact_id IS ?
                                     AND state IN ('queued','running','stop_requested') LIMIT 1""",
                                  (scope.account_id, scope.contact_id)).fetchone()
            if active:
                raise OperationError("operation_already_active", details={"operation_id": active[0]})
            conn.execute("INSERT INTO accounts(account_id) VALUES (?) ON CONFLICT DO NOTHING", (scope.account_id,))
            if scope.contact_id is not None:
                person = conn.execute("SELECT is_self,identity_state FROM contacts WHERE account_id=? AND contact_id=?",
                                      (scope.account_id, scope.contact_id)).fetchone()
                if person is None:
                    raise OperationError("contact_not_found", 404)
                if person[0]:
                    raise OperationError("self_contact_not_target")
                if person[1] != "active":
                    raise OperationError("contact_identity_quarantined")
            operation_id = str(uuid4())
            stamp = now()
            conn.execute("""INSERT INTO operations(account_id,id,contact_id,action,idempotency_key,remaining,
                            counts_json,request_json,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?)""",
                         (scope.account_id, operation_id, scope.contact_id, action, idempotency_key,
                          json.dumps(initial_counts()), encoded, stamp, stamp))
            conn.execute("""INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,phase)
                            VALUES (?,?,'source',?,'source')""", (scope.account_id, operation_id, scope.contact_id))
    return get_operation(conn, scope.account_id, operation_id)


def control_operation(conn, account_id, operation_id, action):
    if action != "stop":
        raise OperationError("unsupported_control", 422)
    with transaction(conn):
        current = get_operation(conn, account_id, operation_id)
        if current.state in {"stopped", "stop_requested"}:
            return current
        if current.state not in {"queued", "running"}:
            raise OperationError("operation_not_stoppable")
        state = "stopped" if current.state == "queued" else "stop_requested"
        conn.execute("UPDATE operations SET state=?,generation=generation+1,updated_at=? WHERE account_id=? AND id=?",
                     (state, now(), account_id, operation_id))
        conn.execute("""UPDATE operation_items SET state='stopped',generation=generation+1,error_code='user_stopped'
                        WHERE account_id=? AND operation_id=? AND state='queued'""", (account_id, operation_id))
    return get_operation(conn, account_id, operation_id)
