"""Bounded page execution with durable per-conversation leases and cancellation."""

import asyncio
import argparse
from collections import Counter
from contextlib import asynccontextmanager
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from pydantic import BaseModel, Field

from ..config import Settings
from ..operations.contracts import OperationScope
from ..storage.db import SCHEMA_VERSION, migrate, open_db
from .adapter import SourceError, WXCLIAdapter
from .probe import SourceConfig, _message_issue
from .repository import archive_metadata, archive_page, cancellation_requested, transaction


class SyncResult(BaseModel):
    elapsed_ms: int = 0
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0
    pages_processed: int = 0
    total_conversations: int = 0
    successful_conversations: list[str] = Field(default_factory=list)
    failed_conversations: list[str] = Field(default_factory=list)
    incomplete_conversations: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conversation_gaps: dict[str,list[str]] = Field(default_factory=dict)
    missing_conversations: list[str] = Field(default_factory=list)
    history_complete: bool = False
    stopped: bool = False
    metadata_people: int = 0
    metadata_groups: int = 0
    names_scoped: int = 0
    names_missing: int = 0
    contacts_total: int | None = None
    contacts_current: int | None = None
    contacts_retained: int | None = None


@asynccontextmanager
async def _lease(conn, account_id, conversation_id):
    owner = str(uuid4())
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        with transaction(conn):
            now = time.time()
            changed = conn.execute("""INSERT INTO sync_leases(account_id,conversation_id,owner,expires_at) VALUES (?,?,?,?)
                                      ON CONFLICT(account_id,conversation_id) DO UPDATE SET owner=excluded.owner,
                                      expires_at=excluded.expires_at WHERE sync_leases.expires_at<?""",
                                   (account_id, conversation_id, owner, now + 120, now)).rowcount
        if changed:
            break
        if asyncio.get_running_loop().time() >= deadline:
            raise SourceError("source_scope_busy")
        await asyncio.sleep(0.05)
    try:
        yield owner
    finally:
        with transaction(conn):
            conn.execute("DELETE FROM sync_leases WHERE account_id=? AND conversation_id=? AND owner=?",
                         (account_id, conversation_id, owner))


def _now():
    return datetime.now(timezone.utc).isoformat()


async def sync_scope(conn, source, scope, cancellation, *, conversation_ids=None, page_size=200,
                     max_pages=1000, from_start=False, sample=False, on_progress=None, metadata_only=False) -> SyncResult:
    result = SyncResult()
    if type(page_size) is not int or not 1 <= page_size <= 500 or type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise SourceError("source_sync_limits_invalid")
    if conn.in_transaction:
        raise SourceError("archive_requires_idle_connection")
    if source.account_id != scope.account_id:
        raise SourceError("source_account_mismatch")
    if cancellation_requested(conn, scope.account_id, cancellation):
        result.gaps = ["source_sync_stopped"]
        result.stopped = True
        return result
    try:
        refresh = getattr(source, 'refresh_metadata', None)
        if callable(refresh):
            await refresh()
        elif metadata_only:
            raise SourceError('source_metadata_refresh_unsupported')
        report = await source.check()
        if report.status != "passed":
            result.gaps = report.gaps or ["source_not_ready"]
            return result
        if report.facts.get('sender_provenance_verified') is False:
            result.gaps = ['source_patch_required']
            return result
        people = await source.contacts()
        rooms = await source.conversations()
        metadata = report.facts.get('metadata')
        if metadata:
            metadata = {**metadata, 'source_version': report.facts.get('cli_version')}
        if archive_metadata(conn, scope.account_id, people, rooms, metadata=metadata, cancellation=cancellation):
            result.gaps.append("source_contact_identity_invalid")
        result.gaps.extend(getattr(source, 'metadata_gaps', []))
        if any(p.remark_state == 'unreadable' or p.nickname_state == 'unreadable' for p in people) or any(r.title_state == 'unreadable' for r in rooms):
            result.gaps.append('source_name_read_failed')
        if any(r.membership_state == 'unreadable' for r in rooms):
            result.gaps.append('source_group_members_unreadable')
        from ..contacts.names import identity_quality
        with transaction(conn):
            quality = identity_quality(conn, scope.account_id)
            total, current = conn.execute('''SELECT COUNT(*),COALESCE(SUM(metadata_current),0)
                FROM contacts WHERE account_id=? AND is_self=0 AND identity_state='active' ''',
                (scope.account_id,)).fetchone()
            result.contacts_total = total
            result.contacts_current = current
            result.contacts_retained = total-current
        result.metadata_people = sum(not person.is_self for person in people)
        result.metadata_groups = sum(room.kind == 'group' for room in rooms)
        result.names_scoped = quality['names_scoped']
        result.names_missing = quality['names_unavailable']
    except SourceError as error:
        result.gaps = [str(error)]
        result.stopped = str(error) == 'source_sync_stopped'
        return result
    if metadata_only:
        return result
    available = {room.conversation_id: room for room in rooms}
    targets = set(available)
    if scope.contact_id is not None:
        if not conn.execute("SELECT 1 FROM contacts WHERE account_id=? AND contact_id=? AND identity_state='active'",
                            (scope.account_id, scope.contact_id)).fetchone():
            raise SourceError("source_contact_unavailable")
        from ..contacts.conversations import resolve_contact_conversations
        from .contracts import ContactKey
        linked = resolve_contact_conversations(conn,ContactKey(account_id=scope.account_id,contact_id=scope.contact_id))
        result.missing_conversations = sorted(linked - targets)
        if result.missing_conversations:
            result.gaps.append('source_conversation_unavailable')
        targets &= linked
    if any(room.kind == 'group' and (room.membership_state != 'known' or not room.member_ids) for room in rooms):
        result.gaps.append("source_group_membership_unverified")
    if conversation_ids is not None:
        requested = set(conversation_ids)
        if not requested <= targets:
            raise SourceError("source_conversation_unavailable")
        targets = requested
    if sample:
        selected = set()
        for kind in ("private", "group"):
            target = next((room.conversation_id for room in rooms if room.kind == kind
                           and room.conversation_id in targets and room.conversation_id != scope.account_id), None)
            if target is None:
                result.gaps.append(f"source_{kind}_sample_unavailable")
            else:
                selected.add(target)
        targets = selected
    result.total_conversations = len(targets)+len(result.missing_conversations)
    if on_progress:
        on_progress(result, None)
    for conversation_id in sorted(targets):
        attempt_id = str(uuid4())
        completed = False
        gaps = []
        try:
            async with _lease(conn, scope.account_id, conversation_id) as owner:
                with transaction(conn):
                    conn.execute("""INSERT INTO sync_attempts(account_id,attempt_id,conversation_id,state,started_at)
                                    VALUES (?,?,?,'running',?)""", (scope.account_id, attempt_id, conversation_id, _now()))
                saved = conn.execute("SELECT cursor,complete,gaps_json FROM sync_cursors WHERE account_id=? AND conversation_id=?",
                                     (scope.account_id, conversation_id)).fetchone()
                saved_cursor = saved[0] if saved else None
                retry_missing_id = saved and 'source_message_id_unavailable' in json.loads(saved[2])
                cursor = None if from_start or (saved and saved[1]) or retry_missing_id else saved_cursor
                seen_cursors, seen_messages = set(), set()
                for _ in range(max_pages):
                    if cancellation_requested(conn, scope.account_id, cancellation):
                        raise SourceError("source_sync_stopped")
                    with transaction(conn):
                        if conn.execute("""UPDATE sync_leases SET expires_at=? WHERE account_id=? AND conversation_id=?
                                           AND owner=? AND expires_at>?""",
                                        (time.time() + 120, scope.account_id, conversation_id, owner, time.time())).rowcount != 1:
                            raise SourceError("source_sync_lease_lost")
                    page = await source.messages(conversation_id, cursor, page_size)
                    if page.account_id != scope.account_id or page.conversation_id != conversation_id:
                        raise SourceError("source_message_scope_mismatch")
                    page_gaps = set(page.gaps)
                    ids = {record.message_id for record in page.records}
                    recoverable = {"source_message_id_unavailable"}
                    if not page_gaps - recoverable:
                        if ids and ids <= seen_messages:
                            page_gaps.add("source_page_no_progress")
                        if not page.complete and not page_gaps and page.next_cursor is None:
                            page_gaps.add("source_cursor_no_progress")
                        if page.next_cursor is not None and (page.next_cursor == cursor or page.next_cursor in seen_cursors):
                            page_gaps.add("source_cursor_no_progress")
                    # Numberless rows remain quarantined. While reading later
                    # pages, keep the saved cursor at the first gap and persist
                    # the incomplete status, including if this read is stopped.
                    prior_gap = bool(gaps)
                    gaps.extend(sorted(page_gaps - set(gaps)))
                    stored_page = page
                    if gaps:
                        stored_page = page.model_copy(update={"gaps": sorted(gaps), "complete": False})
                    archive_cursor = saved_cursor if prior_gap else cursor
                    delta = archive_page(conn, stored_page, expected_cursor=saved_cursor, start_cursor=archive_cursor,
                                         lease_owner=owner, cancellation=cancellation)
                    result.inserted += delta.inserted
                    result.revised += delta.revised
                    result.unchanged += delta.unchanged
                    result.pages_processed += 1
                    if on_progress:
                        on_progress(result, conversation_id)
                    saved_cursor = archive_cursor if gaps else page.next_cursor
                    if set(gaps) - recoverable or page.complete or page.next_cursor is None:
                        completed = page.complete and not gaps
                        break
                    seen_messages.update(ids)
                    seen_cursors.add(page.next_cursor)
                    cursor = page.next_cursor
                else:
                    gaps.append("source_page_limit_reached")
        except SourceError as error:
            gaps.append(str(error))
            if str(error) == "source_sync_stopped":
                result.stopped = True
        except asyncio.CancelledError:
            with transaction(conn):
                conn.execute("UPDATE sync_attempts SET state='stopped',finished_at=? WHERE account_id=? AND attempt_id=?",
                             (_now(), scope.account_id, attempt_id))
            raise
        except sqlite3.Error:
            gaps.append("archive_write_failed")
        with transaction(conn):
            conn.execute("UPDATE sync_attempts SET state=?,finished_at=?,gaps_json=? WHERE account_id=? AND attempt_id=?",
                         ("succeeded" if completed else ("stopped" if result.stopped else "failed"), _now(),
                          json.dumps(sorted(set(gaps))), scope.account_id, attempt_id))
        if completed:
            result.successful_conversations.append(conversation_id)
        elif gaps == ["source_page_limit_reached"]:
            result.incomplete_conversations.append(conversation_id)
        else:
            result.failed_conversations.append(conversation_id)
        result.conversation_gaps[conversation_id]=sorted(set(gaps))
        result.gaps.extend(gaps)
        from .coverage import GLOBAL,LOCAL,WARNINGS
        if any(g in GLOBAL or g not in LOCAL|WARNINGS|{'source_sync_stopped'} for g in gaps):
            break
        if on_progress:
            on_progress(result, conversation_id)
        if result.stopped:
            break
    result.gaps = sorted(set(result.gaps))
    return result


async def _run_cli(args, settings):
    config_path = args.source_config or settings.source_config
    try:
        values = json.loads(config_path.read_text()) if config_path else {}
        values["expected_account_id"] = args.source_account
        config = SourceConfig.model_validate(values)
    except (OSError, ValueError, TypeError):
        raise SourceError("source_config_invalid") from None
    with closing(open_db(settings.data_dir / "archive.sqlite3")) as conn:
        migrate(conn)
        async with WXCLIAdapter(config) as source:
            result = await sync_scope(conn, source, OperationScope(account_id=args.source_account), None,
                                      sample=args.sample, conversation_ids=args.conversation,
                                      page_size=args.page_size, max_pages=args.max_pages, from_start=args.from_start)
        unresolved = conn.execute("SELECT COUNT(*) FROM source_issues WHERE account_id=? AND resolved=0",
                                  (args.source_account,)).fetchone()[0]
        counts = Counter()
        for row in conn.execute("""SELECT i.code,i.raw_json,c.kind FROM source_issues i JOIN conversations c
                                   ON c.account_id=i.account_id AND c.conversation_id=i.conversation_id
                                   WHERE i.account_id=? AND i.resolved=0""", (args.source_account,)):
            code = row[0] if row[0] in {"message_sender_missing", "message_sender_invalid", "message_sender_conflict", "message_contract_invalid", "source_message_id_unavailable"} else "message_contract_invalid"
            technical = _message_issue(json.loads(row[1]), 0, code)
            counts[(code, technical["msg_type"], technical["sub_type"], row[2])] += 1
        summary = [{"code": key[0], "msg_type": key[1], "sub_type": key[2], "conversation_kind": key[3], "count": count}
                   for key, count in counts.most_common(20)]
        return result, unresolved, summary, len(counts) > 20


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only wx-cli sync into the local archive; no model requests.")
    parser.add_argument("--source-account", required=True)
    parser.add_argument("--source-config", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--sample", action="store_true", help="One private and one group, at most two 20-row pages each")
    selection.add_argument("--conversation", action="append", help="Exact source conversation ID; repeat for multiple targets")
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--from-start", action="store_true", help="Replay the selected visible history from its beginning")
    parser.add_argument("--output", type=Path, help="Counts and technical gaps only; originals remain in SQLite")
    args = parser.parse_args(argv)
    if args.sample and (not 1 <= args.page_size <= 20 or not 1 <= args.max_pages <= 2):
        parser.error("sample_limits_exceeded")
    if not 1 <= args.page_size <= 500 or not 1 <= args.max_pages <= 10000:
        parser.error("source_sync_limits_invalid")
    settings = Settings.load()
    database = (settings.data_dir / "archive.sqlite3").resolve()
    config = args.source_config or settings.source_config
    inputs = {database, Path(str(database) + "-wal"), Path(str(database) + "-shm")}
    if config:
        inputs.add(config.resolve())
        if config.resolve() == database:
            parser.error("database_conflicts_with_source_config")
    if args.output and args.output.resolve() in inputs:
        parser.error("report_output_conflicts_with_input")
    try:
        result, unresolved, issue_types, truncated = asyncio.run(_run_cli(args, settings))
    except SourceError as error:
        result, unresolved, issue_types, truncated = SyncResult(gaps=[str(error)]), None, [], False
    except (OSError, ValueError, sqlite3.Error):
        result, unresolved, issue_types, truncated = SyncResult(gaps=["source_sync_failed"]), None, [], False
    from .coverage import WARNINGS
    report = {
        "warnings": sorted(set(result.gaps)&WARNINGS),
        "schema_version": 1, "database_schema_version": SCHEMA_VERSION, "checked_at": _now(),
        "scope": "sample" if args.sample else "selected", "history_complete": False,
        "account_fingerprint": hashlib.sha256(args.source_account.encode()).hexdigest()[:12],
        "status": "partial" if set(result.gaps)-WARNINGS else "passed",
        "counts": {"inserted": result.inserted, "revised": result.revised, "unchanged": result.unchanged,
                   "pages_processed": result.pages_processed, "completed_conversations": len(result.successful_conversations),
                   "incomplete_conversations": len(result.incomplete_conversations),
                   "failed_conversations": len(result.failed_conversations), "unresolved_issues_total": unresolved},
        "gaps": result.gaps,
        "issue_types": issue_types, "issue_types_truncated": truncated,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if set(result.gaps) - WARNINGS - {"source_page_limit_reached"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
