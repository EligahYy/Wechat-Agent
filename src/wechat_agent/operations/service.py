"""Durable intentions and guarded control; no source requests in HTTP creation."""

from datetime import datetime, timezone
import json
from uuid import uuid4

from pydantic import ValidationError

from .reports import OperationReport
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
        "completed_conversations", "failed_conversations", "incomplete_conversations", "analysis_required", "analysis_completed",
        'metadata_people', 'metadata_groups', 'names_scoped', 'names_missing')}


OPERATION_QUERY="""SELECT o.*,COALESCE(o.contact_name_snapshot,NULLIF(c.remark,''),NULLIF(c.nickname,'')) AS display_name,
 r.report_json AS report_payload,s.state AS resolved_source FROM operations o
 LEFT JOIN contacts c ON c.account_id=o.account_id AND c.contact_id=o.contact_id
 LEFT JOIN operation_reports r ON r.account_id=o.account_id AND r.operation_id=o.id
 LEFT JOIN operation_items s ON s.account_id=o.account_id AND s.operation_id=o.id AND s.item_id='source' """

def get_operation(conn, account_id, operation_id, *, include_items=True, _row=None):
    row = _row if _row is not None else conn.execute(OPERATION_QUERY+" WHERE o.account_id=? AND o.id=?", (account_id, operation_id)).fetchone()
    if row is None:
        raise OperationError("operation_not_found", 404)
    try:
        options = SyncOptions.model_validate_json(row["request_json"])
    except ValidationError:
        options = None
    items = []
    if include_items:
        for item in conn.execute("SELECT * FROM operation_items WHERE account_id=? AND operation_id=? ORDER BY phase DESC,item_id",
                                 (account_id, operation_id)):
            items.append(OperationItem(id=item["item_id"], contact_id=item["contact_id"], conversation_id=item["conversation_id"],
                state=item["state"], phase=item["phase"], generation=item["generation"], counts=json.loads(item["counts_json"]),
                gaps=json.loads(item["gaps_json"]), error_code=item["error_code"], role_version=item["role_version"]))
    return Operation(contact_name_snapshot=row["display_name"], report=OperationReport.model_validate_json(row["report_payload"]) if row["report_payload"] else None, id=row["id"], scope=OperationScope(account_id=account_id, contact_id=row["contact_id"]),
        action=row["action"], state=row["state"], phase=row["phase"], generation=row["generation"], remaining=row["remaining"],
        counts=json.loads(row["counts_json"]), error_code=row["error_code"], source_state=row["resolved_source"],
        items=items, options=options, created_at=row["created_at"], updated_at=row["updated_at"])


def create_operation(conn, action, scope, idempotency_key, *, options=None):
    if action not in {"sync", "sync_and_organize", 'refresh_contacts'}:
        raise OperationError("unsupported_action", 422)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key)>256:
        raise OperationError("invalid_idempotency_key", 422)
    scope = OperationScope.model_validate(scope.model_dump())
    if action == 'refresh_contacts' and scope.contact_id is not None:
        raise OperationError('metadata_refresh_account_scope_required', 422)
    options = SyncOptions.model_validate(options.model_dump() if options else {})
    if options.text_strategy == 'relevance' and (action != 'sync_and_organize' or not scope.contact_id):
        raise OperationError('relevance_requires_single_customer', 422)
    encoded = json.dumps(options.model_dump(mode='json'), sort_keys=True)
    with transaction(conn):
        old = conn.execute("SELECT * FROM operations WHERE account_id=? AND idempotency_key=?",
                           (scope.account_id, idempotency_key)).fetchone()
        if old:
            if old["action"] != action or old["contact_id"] != scope.contact_id or SyncOptions.model_validate_json(old["request_json"]) != options:
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
                person = conn.execute("SELECT is_self,identity_state,role FROM contacts WHERE account_id=? AND contact_id=?",
                                      (scope.account_id, scope.contact_id)).fetchone()
                if person is None:
                    raise OperationError("contact_not_found", 404)
                if person[0]:
                    raise OperationError("self_contact_not_target")
                if person[1] != "active":
                    raise OperationError("contact_identity_quarantined")
                if options.text_strategy == 'relevance' and person['role'] != 'merchant':
                    raise OperationError('relevance_requires_merchant', 422)
            if scope.contact_id is not None and action == 'sync_and_organize':
                from ..contacts.scope import decisions
                if not decisions(conn,scope.account_id,contact_ids={scope.contact_id})[scope.contact_id].included:
                    raise OperationError('contact_scope_excluded',409)
            if options.relevance_review_refs:
                from ..contacts.conversations import resolve_contact_conversations
                from ..source.contracts import ContactKey
                rooms = resolve_contact_conversations(conn, ContactKey(account_id=scope.account_id, contact_id=scope.contact_id))
                for ref in options.relevance_review_refs:
                    material = conn.execute(
                        'SELECT conversation_id,revision FROM messages WHERE account_id=? AND message_id=?',
                        (scope.account_id, ref.message_id),
                    ).fetchone()
                    if material is None or material[0] not in rooms or material[1] != ref.revision:
                        raise OperationError('relevance_review_material_changed', 409)
            operation_id = str(uuid4())
            stamp = now()
            conn.execute("""INSERT INTO operations(account_id,id,contact_id,action,idempotency_key,remaining,
                            counts_json,request_json,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?)""",
                         (scope.account_id, operation_id, scope.contact_id, action, idempotency_key,
                          json.dumps(initial_counts()), encoded, stamp, stamp))
            if scope.contact_id:
                name=conn.execute("SELECT COALESCE(NULLIF(remark,''),NULLIF(nickname,''),contact_id) FROM contacts WHERE account_id=? AND contact_id=?",(scope.account_id,scope.contact_id)).fetchone()
                conn.execute('UPDATE operations SET contact_name_snapshot=? WHERE account_id=? AND id=?',(name[0],scope.account_id,operation_id))
            conn.execute("""INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,phase)
                            VALUES (?,?,'source',?,'source')""", (scope.account_id, operation_id, scope.contact_id))
    return get_operation(conn, scope.account_id, operation_id)


def resume_operation(conn, account_id, operation_id):
    previous = get_operation(conn, account_id, operation_id)
    if 'resume' not in previous.available_actions:
        raise OperationError('operation_not_resumable')
    return create_operation(
        conn, previous.action, previous.scope, f'resume:{operation_id}', options=previous.options,
    )


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
