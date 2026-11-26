"""Persist the classification of a frozen snapshot, independently of model coverage."""

import json

from ..context.reader import ContextReader
from ..context.relevance import RelevanceManifest, has_review_gap, reviewable
from ..model.contracts import ModelCallError
from ..source.repository import cancellation_requested, transaction


def selected_refs(snapshot, manifest):
    expected = {(ref.message_id, ref.revision) for ref in snapshot.material_refs}
    entries = {(entry.message_id, entry.revision) for entry in manifest.entries}
    if entries != expected or len(entries) != len(manifest.entries):
        raise ModelCallError('relevance_coverage_incomplete')
    return {(entry.message_id, entry.revision) for entry in manifest.entries if entry.level == 'high'}


def save_relevance(conn, snapshot, token, manifest):
    account, contact = snapshot.key.account_id, snapshot.key.contact_id
    with transaction(conn):
        ContextReader(conn, snapshot)
        selected_refs(snapshot, manifest)
        operation = conn.execute('SELECT contact_id FROM operations WHERE account_id=? AND id=?',
                                 (account, token.operation_id)).fetchone()
        if operation is None or operation[0] != contact or cancellation_requested(conn, account, token):
            raise ModelCallError('model_cancelled')
        encoded = manifest.model_dump_json()
        conn.execute(
            'INSERT INTO message_relevance VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',
            (account, snapshot.id, token.operation_id, contact, encoded),
        )
        saved = conn.execute('SELECT operation_id,manifest_json FROM message_relevance WHERE account_id=? AND snapshot_id=?',
                             (account, snapshot.id)).fetchone()
        if tuple(saved) != (token.operation_id, encoded):
            raise ModelCallError('relevance_manifest_changed')
        conn.execute('DELETE FROM relevance_receipts WHERE account_id=? AND contact_id=? AND snapshot_id<>?',
                     (account, contact, snapshot.id))
        row = conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',
                           (account, token.operation_id)).fetchone()
        counts = json.loads(row[0])
        counts['relevance_total'] = len(manifest.entries)
        counts['relevance_reviewable'] = sum(reviewable(entry) for entry in manifest.entries)
        for level in ('high', 'medium', 'low'):
            counts[f'relevance_{level}'] = sum(entry.level == level for entry in manifest.entries)
        conn.execute('UPDATE operations SET counts_json=? WHERE account_id=? AND id=?',
                     (json.dumps(counts), account, token.operation_id))


def load_relevance(conn, account_id, snapshot_id):
    row = conn.execute('SELECT manifest_json FROM message_relevance WHERE account_id=? AND snapshot_id=?',
                       (account_id, snapshot_id)).fetchone()
    return RelevanceManifest.model_validate_json(row[0]) if row else None


class RelevanceUnchanged(Exception):
    def __init__(self, outcome):
        self.outcome = outcome


def retained_review_refs(conn, snapshot):
    key = snapshot.key
    row = conn.execute(
        """SELECT s.manifest_json,r.manifest_json FROM message_relevance r JOIN snapshots s
           ON s.account_id=r.account_id AND s.snapshot_id=r.snapshot_id
           JOIN operations o ON o.account_id=r.account_id AND o.id=r.operation_id
           WHERE r.account_id=? AND r.contact_id=? AND r.snapshot_id<>?
           ORDER BY o.created_at DESC,o.rowid DESC LIMIT 1""",
        (key.account_id, key.contact_id, snapshot.id),
    ).fetchone()
    if row is None:
        return set()
    old = json.loads(row[0])
    if old['role_version'] != snapshot.role_version or old.get('scope_version', 0) != snapshot.scope_version:
        return set()
    return {(entry.message_id, entry.revision) for entry in RelevanceManifest.model_validate_json(row[1]).entries
            if 'reviewed' in entry.reason_codes}


def finish_without_model(conn, snapshot, token, manifest):
    from ..profiles.publisher import check_inputs
    from ..profiles.status import inputs_match

    key = snapshot.key
    if any(has_review_gap(entry) for entry in manifest.entries):
        return
    high = selected_refs(snapshot, manifest)
    outcome = None
    with transaction(conn):
        _, head, reason = check_inputs(conn, snapshot, token)
        if reason:
            raise ModelCallError(reason)
        if not inputs_match(conn, key, snapshot.model_dump_json(), manual_version=snapshot.manual_version,
                            role_version=snapshot.role_version, scope_version=snapshot.scope_version):
            raise ModelCallError('material_changed')
        if not snapshot.profile_version and not high:
            outcome = 'no_relevant_material'
        elif snapshot.profile_version and head and head['version'] == snapshot.profile_version:
            prior = conn.execute(
                """SELECT s.manifest_json,r.manifest_json,s.payload_json FROM profile_versions p
                   JOIN snapshots s ON s.account_id=p.account_id AND s.snapshot_id=p.snapshot_id
                   JOIN message_relevance r ON r.account_id=p.account_id AND r.snapshot_id=p.snapshot_id
                   WHERE p.account_id=? AND p.contact_id=? AND p.version=? AND p.pending=0""",
                (key.account_id, key.contact_id, snapshot.profile_version),
            ).fetchone()
            if prior:
                old = json.loads(prior[0])
                current = snapshot.model_dump(mode='json')
                stable = all(old.get(field) == current.get(field) for field in
                             ('role_version', 'scope_version', 'manual_version', 'versions', 'gaps', 'coverage'))
                before = RelevanceManifest.model_validate_json(prior[1])
                old_context = [entry for entry in before.entries if entry.level != 'low']
                new_context = [entry for entry in manifest.entries if entry.level != 'low']
                payload = json.loads(prior[2])
                reader = ContextReader(conn, snapshot)
                actors = reader.actors()
                if (stable and before.rule_version == manifest.rule_version and old_context == new_context
                        and payload['conversations'] == reader.conversations()
                        and all(actors.get(identifier) == value for identifier, value in payload['actors'].items())):
                    outcome = 'unchanged'
        if outcome:
            conn.execute(
                """INSERT INTO relevance_receipts VALUES(?,?,?,?,?) ON CONFLICT(account_id,contact_id)
                   DO UPDATE SET snapshot_id=excluded.snapshot_id,profile_version=excluded.profile_version,
                     outcome=excluded.outcome""",
                (key.account_id, key.contact_id, snapshot.id, snapshot.profile_version, outcome),
            )
    if outcome:
        raise RelevanceUnchanged(outcome)
