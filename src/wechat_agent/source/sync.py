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
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0
    pages_processed: int = 0
    successful_conversations: list[str] = Field(default_factory=list)
    failed_conversations: list[str] = Field(default_factory=list)
    incomplete_conversations: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    history_complete: bool = False
    stopped: bool = False


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
                     max_pages=1000, from_start=False, sample=False) -> SyncResult:
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
        report = await source.check()
        if report.status != "passed":
            result.gaps = report.gaps or ["source_not_ready"]
            return result
        people = await source.contacts()
        rooms = await source.conversations()
        archive_metadata(conn, scope.account_id, people, rooms)
    except SourceError as error:
        result.gaps = [str(error)]
        return result
    available = {room.conversation_id: room for room in rooms}
    targets = set(available)
    if scope.contact_id is not None:
        if not any(person.key.contact_id == scope.contact_id for person in people):
            raise SourceError("source_contact_unavailable")
        linked = {row[0] for row in conn.execute("SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?",
                                               (scope.account_id, scope.contact_id))}
        linked.add(scope.contact_id)
        targets &= linked
        if any(room.kind == "group" and not conn.execute(
                "SELECT 1 FROM members WHERE account_id=? AND conversation_id=? LIMIT 1",
                (scope.account_id, room.conversation_id)).fetchone() for room in rooms):
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
    for conversation_id in sorted(targets):
        attempt_id = str(uuid4())
        completed = False
        gaps = []
        try:
            async with _lease(conn, scope.account_id, conversation_id) as owner:
                with transaction(conn):
                    conn.execute("""INSERT INTO sync_attempts(account_id,attempt_id,conversation_id,state,started_at)
                                    VALUES (?,?,?,'running',?)""", (scope.account_id, attempt_id, conversation_id, _now()))
                saved = conn.execute("SELECT cursor,complete FROM sync_cursors WHERE account_id=? AND conversation_id=?",
                                     (scope.account_id, conversation_id)).fetchone()
                saved_cursor = saved[0] if saved else None
                cursor = None if from_start or (saved and saved[1]) else saved_cursor
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
                    page_gaps = list(page.gaps)
                    ids = {record.message_id for record in page.records}
                    if not page_gaps:
                        if ids and ids <= seen_messages:
                            page_gaps.append("source_page_no_progress")
                    if not page.complete and not page_gaps:
                        if page.next_cursor is None or page.next_cursor == cursor or page.next_cursor in seen_cursors:
                            page_gaps.append("source_cursor_no_progress")
                    if page_gaps != page.gaps:
                        page = page.model_copy(update={"gaps": sorted(set(page_gaps)), "complete": False})
                    delta = archive_page(conn, page, expected_cursor=saved_cursor, start_cursor=cursor,
                                         lease_owner=owner, cancellation=cancellation)
                    result.inserted += delta.inserted
                    result.revised += delta.revised
                    result.unchanged += delta.unchanged
                    result.pages_processed += 1
                    if page.gaps:
                        gaps.extend(page.gaps)
                        break
                    saved_cursor = page.next_cursor
                    seen_messages.update(ids)
                    if page.complete:
                        completed = True
                        break
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
        result.gaps.extend(gaps)
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
            code = row[0] if row[0] in {"message_sender_missing", "message_contract_invalid", "source_message_id_unavailable"} else "message_contract_invalid"
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
    report = {
        "schema_version": 1, "database_schema_version": SCHEMA_VERSION, "checked_at": _now(),
        "scope": "sample" if args.sample else "selected", "history_complete": False,
        "account_fingerprint": hashlib.sha256(args.source_account.encode()).hexdigest()[:12],
        "status": "partial" if result.gaps else "passed",
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
    return 1 if set(result.gaps) - {"source_page_limit_reached"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
