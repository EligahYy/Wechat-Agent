"""Account-scoped contact reads and optimistic manual role changes."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..source.contracts import ContactKey
from .names import load_catalog, resolve_name, identity_quality, metadata_status, present_source_title, match_contact_names


Role = Literal["merchant", "provider", "platform", "unknown"]
ROLES = ("merchant", "provider", "platform", "unknown")


class ContactError(Exception):
    def __init__(self, code, status=409):
        self.code = code
        self.status = status
        super().__init__(code)


class RoleChange(BaseModel):
    key: ContactKey
    role: Role
    role_version: int
    changed: bool
    cancelled_analysis_items: int = 0
    cancelled_operations: int = 0


class RoleFailure(BaseModel):
    key: ContactKey
    code: str
    current_version: int | None = None


class RoleUpdateResult(BaseModel):
    status: Literal["succeeded", "partial", "failed"] = "succeeded"
    updated: list[RoleChange] = Field(default_factory=list)
    failed: list[RoleFailure] = Field(default_factory=list)


def _filters(account_id, q, role=None, *, matching_rowids=None):
    clauses = ["c.account_id=?", "c.is_self=0", "c.identity_state='active'"]
    params = [account_id]
    if q:
        # These integer rowids come from this account's database snapshot, never
        # from query text. Integer literals avoid SQLite's parameter-count limit
        # when a common name matches thousands of people.
        ids = ','.join(str(int(rowid)) for rowid in (matching_rowids or []))
        clauses.append(f"c.rowid IN ({ids})" if ids else "0")
    if role and role != "all":
        clauses.append("c.role=?")
        params.append(role)
    return " AND ".join(clauses), params


def _source_gaps(conn, account_id, contact_id):
    gaps = set()
    scopes = """SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?"""
    params = (account_id, account_id, contact_id)
    for row in conn.execute(f"SELECT complete,gaps_json FROM sync_cursors WHERE account_id=? AND conversation_id IN ({scopes})", params):
        gaps.update(json.loads(row[1]))
        if not row[0]:
            gaps.add("source_history_incomplete")
    for row in conn.execute(f"SELECT code FROM source_issues WHERE account_id=? AND resolved=0 AND conversation_id IN ({scopes})", params):
        gaps.add(row[0])
    for row in conn.execute(f"""SELECT a.gaps_json FROM sync_attempts a WHERE a.account_id=?
                            AND a.conversation_id IN ({scopes}) AND NOT EXISTS (
                            SELECT 1 FROM sync_attempts b WHERE b.account_id=a.account_id
                            AND b.conversation_id=a.conversation_id
                            AND (b.started_at>a.started_at OR (b.started_at=a.started_at AND b.attempt_id>a.attempt_id)))""", params):
        gaps.update(json.loads(row[0]))
    return sorted(gaps)


def list_contacts(conn, account_id, *, q="", role="all", page=1, page_size=20):
    if role not in ("all", *ROLES) or not 1 <= page_size <= 20 or page < 1:
        raise ContactError("invalid_contact_query", 422)
    q = q.strip()
    catalog = load_catalog(conn, account_id)
    matching_rowids, presentations = (None, None)
    if q:
        matching_rowids, presentations = match_contact_names(conn, account_id, q, catalog)
    where, params = _filters(account_id, q, role, matching_rowids=matching_rowids)
    base_where, base_params = _filters(account_id, q, matching_rowids=matching_rowids)
    total = conn.execute(f"SELECT COUNT(*) FROM contacts c WHERE {where}", params).fetchone()[0]
    counts = {name: 0 for name in ROLES}
    for row in conn.execute(f"SELECT c.role,COUNT(*) FROM contacts c WHERE {base_where} GROUP BY c.role", base_params):
        counts[row[0]] = row[1]
    # Preserve each matching person's latest authored/related message, while
    # avoiding full-account window sorts for a narrow search.
    message_scope = """AND (sender_id IN (SELECT contact_id FROM eligible) OR conversation_id IN (
        SELECT s.conversation_id FROM members s JOIN eligible c
        ON c.account_id=s.account_id AND c.contact_id=s.contact_id))""" if q.strip() else ""
    rows = conn.execute(f"""WITH eligible AS (SELECT c.* FROM contacts c WHERE {where}),
        latest AS (SELECT conversation_id,sender_id,sent_at,message_id,
            ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY julianday(sent_at) DESC,message_id DESC) AS conversation_position,
            ROW_NUMBER() OVER (PARTITION BY sender_id ORDER BY julianday(sent_at) DESC,message_id DESC) AS sender_position
            FROM messages WHERE account_id=? {message_scope}),
        related AS (
            SELECT c.contact_id,m.sent_at,m.message_id FROM eligible c JOIN latest m
                ON m.sender_id=c.contact_id AND m.sender_position=1
            UNION ALL
            SELECT c.contact_id,m.sent_at,m.message_id FROM eligible c JOIN members s
                ON s.account_id=c.account_id AND s.contact_id=c.contact_id
                JOIN latest m ON m.conversation_id=s.conversation_id AND m.conversation_position=1),
        recent AS (SELECT contact_id,sent_at,ROW_NUMBER() OVER (
            PARTITION BY contact_id ORDER BY julianday(sent_at) DESC,message_id DESC) AS position FROM related)
        SELECT c.*,r.sent_at AS last_message_at FROM eligible c LEFT JOIN recent r
            ON r.contact_id=c.contact_id AND r.position=1
        ORDER BY julianday(r.sent_at) DESC,
            COALESCE(NULLIF(trim(c.remark),''),NULLIF(trim(c.nickname),''),'') COLLATE NOCASE,c.contact_id
        LIMIT ? OFFSET ?""", [*params, account_id, page_size, (page - 1) * page_size]).fetchall()
    items = []
    for row in rows:
        presentation = resolve_name(row, catalog[row['contact_id']])
        sources = [dict(source) for source in conn.execute("""SELECT v.conversation_id,v.kind,v.title,v.provenance,v.title_state,
                      EXISTS(SELECT 1 FROM messages m WHERE m.account_id=v.account_id
                             AND m.conversation_id=v.conversation_id) AS has_messages FROM members s
                      JOIN conversations v ON v.account_id=s.account_id AND v.conversation_id=s.conversation_id
                      WHERE s.account_id=? AND s.contact_id=? ORDER BY v.kind,v.conversation_id""",
                    (account_id, row["contact_id"]))]
        for source in sources:
            source['title'] = present_source_title(source['title'], source['conversation_id'])
            source['has_messages'] = bool(source['has_messages'])
        items.append({"key": {"account_id": account_id, "contact_id": row["contact_id"]},
                      **presentation,
                      "role": row["role"], "role_version": row["role_version"], "sources": sources,
                      "last_message_at": row["last_message_at"], "last_business_at": None,
                      "profile_status": ("pending" if row["last_message_at"] else "no_data") if row["role"] == "merchant" else None,
                      "profile_updated_at": None, "source_gaps": _source_gaps(conn, account_id, row["contact_id"])})
    quality = identity_quality(conn, account_id, catalog, presentations)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "role_counts": {"all": sum(counts.values()), **counts}, "identity_quality": quality,
            "metadata_status": metadata_status(conn, account_id)}


def set_roles(conn, keys: list[ContactKey], role: str, expected_versions: dict[str, int]) -> RoleUpdateResult:
    if role not in ROLES or not keys:
        raise ContactError("invalid_role_batch", 422)
    keys = [ContactKey.model_validate(key.model_dump()) for key in keys]
    if len(set(keys)) != len(keys) or len({key.account_id for key in keys}) != 1:
        raise ContactError("invalid_role_batch", 422)
    if conn.in_transaction:
        raise ContactError("role_write_requires_idle_connection")
    result = RoleUpdateResult()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key in keys:
            row = conn.execute("SELECT role,role_version,is_self,identity_state FROM contacts WHERE account_id=? AND contact_id=?",
                               (key.account_id, key.contact_id)).fetchone()
            code = None
            expected = expected_versions.get(key.contact_id)
            if row is None:
                code = "contact_not_found"
            elif row[2]:
                code = "self_role_locked"
            elif row[3] != "active":
                code = "contact_identity_quarantined"
            elif type(expected) is not int or not 1 <= expected <= 2**63 - 1:
                code = "expected_version_required"
            elif row[1] != expected:
                code = "role_version_conflict"
            if code:
                result.failed.append(RoleFailure(key=key, code=code, current_version=row[1] if row else None))
                continue
            changed = row[0] != role
            cancelled_items = cancelled_operations = 0
            if changed:
                conn.execute("""UPDATE contacts SET role=?,role_version=role_version+1
                                WHERE account_id=? AND contact_id=? AND role_version=?""",
                             (role, key.account_id, key.contact_id, expected))
                if role != "merchant":
                    cancelled_items = conn.execute("""UPDATE operation_items SET state='stopped',generation=generation+1,
                        error_code='contact_not_merchant' WHERE account_id=? AND contact_id=? AND state='queued'
                        AND phase='analysis'""", (key.account_id, key.contact_id)).rowcount
                    cancelled_operations = conn.execute("""UPDATE operations SET state='stopped',generation=generation+1,
                        error_code='contact_not_merchant',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE account_id=? AND contact_id=? AND state='queued' AND phase='analysis'""",
                        (key.account_id, key.contact_id)).rowcount
            result.updated.append(RoleChange(key=key, role=role, role_version=expected + int(changed), changed=changed,
                                             cancelled_analysis_items=cancelled_items, cancelled_operations=cancelled_operations))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    result.status = "partial" if result.failed and result.updated else "failed" if result.failed else "succeeded"
    return result
