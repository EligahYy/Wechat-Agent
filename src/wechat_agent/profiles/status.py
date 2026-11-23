"""Project persisted archive and operation facts into customer-facing states."""

import json
from typing import Literal

from ..contacts.conversations import CONTACT_CONVERSATIONS_SQL, conversation_params
from ..source.contracts import ContactKey


ProfileStatus = Literal['no_data', 'pending', 'no_findings', 'manual', 'ready', 'incomplete', 'needs_update']
ProfileFilter = Literal['all', 'no_data', 'pending', 'no_findings', 'manual', 'ready', 'incomplete', 'needs_update']


def material_rows(conn, key, columns):
    return conn.execute(
        f"""SELECT {columns} FROM messages WHERE account_id=? AND
            conversation_id IN ({CONTACT_CONVERSATIONS_SQL})""",
        (key.account_id, *conversation_params(key)),
    )


def inputs_match(conn, key, manifest, *, manual_version, role_version, scope_version):
    frozen = json.loads(manifest)
    if (frozen['manual_version'], frozen['role_version'], frozen.get('scope_version', 0)) != (
        manual_version, role_version, scope_version,
    ):
        return False
    expected = {(ref['message_id'], ref['revision']) for ref in frozen['material_refs']}
    return {tuple(row) for row in material_rows(conn, key, 'message_id,revision')} == expected


def profile_status_for_row(conn, row, scope_version) -> ProfileStatus | None:
    if row['role'] != 'merchant':
        return None
    key = ContactKey(account_id=row['account_id'], contact_id=row['contact_id'])
    return archive_status(
        conn, key, manifest=row['profile_manifest'], has_manual=row['profile_has_manual'],
        complete=row['profile_complete'], pending=row['profile_pending'],
        manual_version=row['profile_manual_version'], role_version=row['role_version'],
        scope_version=scope_version,
    )


def archive_status(conn, key, *, manifest, has_manual, complete, pending,
                   manual_version, role_version, scope_version) -> ProfileStatus:
    versions = dict(manual_version=manual_version, role_version=role_version, scope_version=scope_version)
    receipt = conn.execute(
        """SELECT s.manifest_json,r.outcome,json_extract(s.payload_json,'$.actors') FROM relevance_receipts r JOIN snapshots s
           ON s.account_id=r.account_id AND s.snapshot_id=r.snapshot_id
           WHERE r.account_id=? AND r.contact_id=? AND r.profile_version=COALESCE(
             (SELECT version FROM profile_heads WHERE account_id=? AND contact_id=?),0)""",
        (key.account_id, key.contact_id, key.account_id, key.contact_id),
    ).fetchone()
    current_receipt = receipt and inputs_match(conn, key, receipt[0], **versions)
    if current_receipt:
        actors = json.loads(receipt[2])
        for identifier, old in actors.items():
            current = conn.execute(
                'SELECT role_version,identity_state,is_self FROM contacts WHERE account_id=? AND contact_id=?',
                (key.account_id, identifier),
            ).fetchone()
            if current is None or tuple(current) != (old['role_version'], 'active', int(old['is_self'])):
                current_receipt = False
                break
    if manifest is not None:
        if pending or not current_receipt and not inputs_match(conn, key, manifest, **versions):
            return 'needs_update'
        return 'ready' if complete else 'incomplete'
    if has_manual:
        return 'manual'
    if material_rows(conn, key, '1').fetchone() is None:
        return 'no_data'
    if current_receipt and receipt[1] == 'no_relevant_material':
        return 'no_findings'
    empty = conn.execute(
        """SELECT s.manifest_json
           FROM history_runs h JOIN operation_items i
             ON i.account_id=h.account_id AND i.operation_id=h.operation_id
             AND i.item_id=? AND i.contact_id=h.contact_id AND i.state='failed'
           JOIN operations o ON o.account_id=h.account_id AND o.id=h.operation_id
           JOIN snapshots s ON s.account_id=h.account_id AND s.snapshot_id=h.snapshot_id
           WHERE h.account_id=? AND h.contact_id=? AND i.error_code='empty_result'
           ORDER BY o.created_at DESC, o.rowid DESC LIMIT 1""",
        ('analysis:' + key.contact_id, key.account_id, key.contact_id),
    ).fetchone()
    return 'no_findings' if empty and inputs_match(conn, key, empty[0], **versions) else 'pending'


def latest_organization(conn, row):
    contact_id = row['contact_id']
    attempt = conn.execute(
        """SELECT o.id, o.state AS operation_state, o.phase AS operation_phase,
                  o.error_code AS operation_error, i.state AS item_state, i.error_code AS item_error,
                  json_extract(i.counts_json,'$.skipped') AS skipped
           FROM operations o LEFT JOIN operation_items i
             ON i.account_id=o.account_id AND i.operation_id=o.id AND i.item_id=?
             AND i.contact_id=? AND i.phase='analysis'
           WHERE o.account_id=? AND o.action='sync_and_organize'
             AND (o.contact_id=? OR (o.contact_id IS NULL AND i.item_id IS NOT NULL))
             AND (i.role_version IS NULL OR i.role_version=?)
           ORDER BY o.created_at DESC, o.rowid DESC LIMIT 1""",
        ('analysis:' + contact_id, contact_id, row['account_id'], contact_id, row['role_version']),
    ).fetchone()
    if attempt is None:
        return None
    state = attempt['item_state'] or attempt['operation_state']
    reason = attempt['item_error'] if attempt['item_state'] else attempt['operation_error']
    if state in {'queued', 'running'} and attempt['operation_state'] in {'failed', 'stopped', 'stop_requested'}:
        state = attempt['operation_state']
        reason = attempt['operation_error']
    if state == 'succeeded':
        if attempt['item_state'] is None or reason == 'no_relevant_material':
            status = 'not_applicable'
        elif attempt['skipped']:
            status = 'unchanged'
        else:
            status = 'partial' if reason == 'analysis_incomplete' else 'updated'
    elif reason in {'analysis_budget_paused', 'operation_interrupted'}:
        status = 'paused'
    elif reason == 'empty_result':
        status = 'no_findings'
    elif reason == 'source_not_complete' or (state == 'failed' and attempt['operation_phase'] == 'source'):
        status = 'source_incomplete'
    elif state == 'running':
        status = 'organizing' if attempt['item_state'] or attempt['operation_phase'] == 'analysis' else 'syncing'
    else:
        status = state
    return {'operation_id': attempt['id'], 'status': status, 'reason': reason}
