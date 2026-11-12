"""Archive a validated source page and its cursor in one SQLite transaction."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import time
from uuid import uuid4

from pydantic import ValidationError

from .adapter import SourceError
from .contracts import ContactKey, ContactRecord, ConversationRecord, SourcePage
from ..identities import is_person_identifier
from .names import start_metadata, archive_room_names, finish_metadata


@dataclass(slots=True)
class ArchiveDelta:
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0


@contextmanager
def transaction(conn):
    if conn.in_transaction:
        raise SourceError("archive_requires_idle_connection")
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _account(conn, account_id):
    if not account_id.strip():
        raise SourceError("source_account_missing")
    conn.execute("INSERT INTO accounts(account_id) VALUES (?) ON CONFLICT DO NOTHING", (account_id,))


def _person(conn, account_id, contact_id):
    try:
        ContactKey(account_id=account_id, contact_id=contact_id)
    except ValidationError:
        raise SourceError("source_sender_identity_invalid") from None
    valid = is_person_identifier(contact_id)
    conn.execute("""INSERT INTO contacts(account_id,contact_id,is_self,identity_state,identity_reason) VALUES (?,?,?,?,?)
                    ON CONFLICT DO NOTHING""", (account_id, contact_id, int(contact_id == account_id),
                    "active" if valid else "quarantined", None if valid else "source_identity_invalid"))


def archive_metadata(conn, account_id, contacts, conversations, *, metadata=None, cancellation=None):
    try:
        contacts = [ContactRecord.model_validate(person.model_dump()) for person in contacts]
        conversations = [ConversationRecord.model_validate(room.model_dump()) for room in conversations]
    except (ValidationError, AttributeError):
        raise SourceError('source_metadata_contract_invalid') from None
    if any(person.key.account_id != account_id for person in contacts) or any(
            room.account_id != account_id for room in conversations):
        raise SourceError("source_metadata_scope_mismatch")
    invalid = set()
    with transaction(conn):
        if cancellation_requested(conn, account_id, cancellation):
            raise SourceError('source_sync_stopped')
        _account(conn, account_id)
        now = start_metadata(conn, account_id)
        for person in contacts:
            valid = is_person_identifier(person.key.contact_id)
            if not valid:
                invalid.add(person.key.contact_id)
            conn.execute("""INSERT INTO contacts(account_id,contact_id,remark,nickname,is_self,identity_state,identity_reason,
                            remark_state,nickname_state,metadata_current,metadata_seen_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)
                            ON CONFLICT(account_id,contact_id) DO UPDATE SET
                            remark=CASE WHEN excluded.remark_state IN ('known','empty') THEN excluded.remark ELSE contacts.remark END,
                            nickname=CASE WHEN excluded.nickname_state IN ('known','empty') THEN excluded.nickname ELSE contacts.nickname END,
                            is_self=excluded.is_self,identity_state=excluded.identity_state,identity_reason=excluded.identity_reason,
                            remark_state=excluded.remark_state,nickname_state=excluded.nickname_state,
                            metadata_current=1,metadata_seen_at=excluded.metadata_seen_at""",
                         (account_id, person.key.contact_id, person.remark, person.nickname, int(person.is_self),
                          "active" if valid else "quarantined", None if valid else "source_identity_invalid",
                          person.remark_state, person.nickname_state, now))
        for room in conversations:
            conn.execute("""INSERT INTO conversations(account_id,conversation_id,kind,title,provenance,title_state) VALUES (?,?,?,?,?,?)
                            ON CONFLICT(account_id,conversation_id) DO UPDATE SET kind=excluded.kind,
                            title=CASE WHEN excluded.title_state IN ('known','empty') THEN excluded.title ELSE conversations.title END,
                            provenance=excluded.provenance,title_state=excluded.title_state""",
                         (account_id, room.conversation_id, room.kind, room.title, room.origin, room.title_state))
            for member in room.member_ids:
                if not is_person_identifier(member):
                    invalid.add(member)
                if room.kind == 'group' and room.membership_state == 'known' and not conn.execute(
                        'SELECT 1 FROM contacts WHERE account_id=? AND contact_id=?', (account_id, member)).fetchone():
                    continue
                _person(conn, account_id, member)
                if not is_person_identifier(member):
                    invalid.add(member)
                conn.execute("""INSERT INTO members(account_id,conversation_id,contact_id,provenance)
                                VALUES (?,?,?,'source_membership') ON CONFLICT DO NOTHING""",
                             (account_id, room.conversation_id, member))
            archive_room_names(conn, account_id, room, now)
        finish_metadata(conn, account_id, contacts, conversations, metadata, now)
        if cancellation_requested(conn, account_id, cancellation):
            raise SourceError('source_sync_stopped')
    return len(invalid)


def cancellation_requested(conn, account_id, cancellation):
    if cancellation is None:
        return False
    row = conn.execute("SELECT generation,state FROM operations WHERE account_id=? AND id=?",
                       (account_id, cancellation.operation_id)).fetchone()
    return row is None or row[0] != cancellation.generation or row[1] not in {"queued", "running"}


_UNSET = object()


def archive_page(conn, page: SourcePage, *, expected_cursor=_UNSET, start_cursor=_UNSET,
                 lease_owner=None, cancellation=None) -> ArchiveDelta:
    try:
        page = SourcePage.model_validate(page.model_dump())
    except ValidationError:
        raise SourceError("source_message_contract_invalid") from None
    with transaction(conn):
        return _archive_page_locked(conn,page,expected_cursor=expected_cursor,start_cursor=start_cursor,
            lease_owner=lease_owner,cancellation=cancellation)


def _archive_page_locked(conn,page,*,expected_cursor=_UNSET,start_cursor=_UNSET,
                         lease_owner=None,cancellation=None,preserve_cursor=False,imports_only=False):
    delta = ArchiveDelta()
    if cancellation_requested(conn, page.account_id, cancellation):
        raise SourceError("source_sync_stopped")
    if lease_owner is not None:
        lease = conn.execute("SELECT owner,expires_at FROM sync_leases WHERE account_id=? AND conversation_id=?",
                             (page.account_id, page.conversation_id)).fetchone()
        if lease is None or lease[0] != lease_owner or lease[1] <= time.time():
            raise SourceError("source_sync_lease_lost")
    current = conn.execute("SELECT cursor FROM sync_cursors WHERE account_id=? AND conversation_id=?",
                           (page.account_id, page.conversation_id)).fetchone()
    saved_cursor = current[0] if current else None
    if expected_cursor is not _UNSET and saved_cursor != expected_cursor:
        raise SourceError("source_cursor_changed")
    _account(conn, page.account_id)
    room = conn.execute("SELECT kind FROM conversations WHERE account_id=? AND conversation_id=?",
                        (page.account_id, page.conversation_id)).fetchone()
    kind = page.conversation_kind or ("group" if page.conversation_id.endswith("@chatroom") else "private")
    if room is not None and page.conversation_kind is not None and room[0] != kind:
        raise SourceError("source_conversation_kind_mismatch")
    conn.execute("INSERT INTO conversations(account_id,conversation_id,kind) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                 (page.account_id, page.conversation_id, kind))
    for item in page.records:
        if item.sender_id is not None:
            _person(conn, page.account_id, item.sender_id)
            conn.execute("INSERT INTO members(account_id,conversation_id,contact_id) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                         (page.account_id, page.conversation_id, item.sender_id))
        raw = json.dumps(item.raw, ensure_ascii=False, sort_keys=True)
        values = (item.sender_id, item.sent_at.isoformat(), item.kind, item.body, item.reply_to, item.source_revision, raw)
        old = conn.execute("""SELECT conversation_id,revision,sender_id,sent_at,kind,body,reply_to,source_revision,raw_json
                              FROM messages WHERE account_id=? AND message_id=?""",
                           (page.account_id, item.message_id)).fetchone()
        if old and imports_only:
            raise SourceError('import_existing_message_write_refused')
        if old and old[0] != page.conversation_id:
            raise SourceError("source_message_identity_conflict")
        if old and tuple(old[2:]) == values:
            delta.unchanged += 1
        else:
            if old and old[7] == item.source_revision:
                raise SourceError("source_revision_conflict")
            revision = old[1] + 1 if old else 1
            conn.execute("""INSERT INTO messages(account_id,message_id,conversation_id,revision,
                            sender_id,sent_at,kind,body,reply_to,source_revision,raw_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,message_id) DO UPDATE SET
                            revision=excluded.revision,sender_id=excluded.sender_id,sent_at=excluded.sent_at,
                            kind=excluded.kind,body=excluded.body,reply_to=excluded.reply_to,
                            source_revision=excluded.source_revision,raw_json=excluded.raw_json""",
                         (page.account_id, item.message_id, page.conversation_id, revision, *values))
            conn.execute("""INSERT INTO message_revisions(account_id,message_id,revision,
                            sender_id,sent_at,kind,body,reply_to,source_revision,raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (page.account_id, item.message_id, revision, *values))
            if old:
                delta.revised += 1
            else:
                delta.inserted += 1
        for attachment_id in item.attachment_ids:
            existing = conn.execute("SELECT message_id FROM attachments WHERE account_id=? AND attachment_id=?",
                                    (page.account_id, attachment_id)).fetchone()
            if existing and existing[0] != item.message_id:
                raise SourceError("source_attachment_identity_conflict")
            conn.execute("INSERT INTO attachments(account_id,attachment_id,message_id) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                         (page.account_id, attachment_id, item.message_id))
        conn.execute("UPDATE source_issues SET resolved=1 WHERE account_id=? AND conversation_id=? AND message_id=?",
                     (page.account_id, page.conversation_id, item.message_id))
    for issue in page.issues:
        raw = json.dumps(issue.raw, ensure_ascii=False, sort_keys=True)
        conn.execute("""INSERT INTO source_issues(account_id,issue_id,conversation_id,message_id,source_revision,code,raw_json)
                        VALUES (?,?,?,?,?,?,?) ON CONFLICT(account_id,conversation_id,message_id,source_revision,code)
                        DO UPDATE SET resolved=0""",
                     (page.account_id, str(uuid4()), page.conversation_id, issue.message_id,
                      hashlib.sha256(raw.encode()).hexdigest(), issue.code, raw))
    if not preserve_cursor:
        cursor = (saved_cursor if start_cursor is _UNSET else start_cursor) if page.gaps else page.next_cursor
        conn.execute("""INSERT INTO sync_cursors(account_id,conversation_id,cursor,complete,gaps_json) VALUES (?,?,?,?,?)
                        ON CONFLICT(account_id,conversation_id) DO UPDATE SET cursor=excluded.cursor,complete=excluded.complete,
                        gaps_json=excluded.gaps_json,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                     (page.account_id, page.conversation_id, cursor, int(page.complete and not page.gaps), json.dumps(page.gaps)))
    return delta
