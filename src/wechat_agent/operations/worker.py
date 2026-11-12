"""One guarded source worker; analysis remains explicitly unavailable in M1."""

import asyncio
from contextlib import asynccontextmanager, closing
import json
import logging
import os
import sqlite3
from uuid import uuid4

from pydantic import ValidationError

from .contracts import CancellationToken, SyncOptions
from .service import get_operation, initial_counts, now
from ..source.adapter import SourceError
from ..source.repository import transaction
from ..source.sync import sync_scope
from ..storage.db import open_existing_db


def _claim(conn, account_id):
    owner = f"{os.getpid()}:{uuid4()}"
    with transaction(conn):
        row = conn.execute("""SELECT o.* FROM operations o WHERE o.state='queued'
            AND o.action IN ('sync','sync_and_organize','refresh_contacts') AND (? IS NULL OR o.account_id=?)
            AND NOT EXISTS(SELECT 1 FROM operations r WHERE r.account_id=o.account_id
                AND r.state IN ('running','stop_requested')) ORDER BY o.created_at,o.rowid LIMIT 1""",
            (account_id, account_id)).fetchone()
        if row is None:
            return None
        changed = conn.execute("""UPDATE operations SET state='running',phase='source',worker_id=?,updated_at=?
                                 WHERE account_id=? AND id=? AND state='queued'""",
                               (owner, now(), row["account_id"], row["id"])).rowcount
        if changed != 1:
            return None
        conn.execute("""UPDATE operation_items SET state='running',generation=? WHERE account_id=?
                        AND operation_id=? AND item_id='source'""", (row["generation"], row["account_id"], row["id"]))
    return get_operation(conn, row["account_id"], row["id"]), owner, row["request_json"]


@asynccontextmanager
async def _source(services, account_id):
    if services.source is not None:
        if services.source.account_id != account_id:
            raise SourceError("source_account_mismatch")
        yield services.source
    elif services.source_factory is not None:
        async with services.source_factory(account_id) as source:
            if source.account_id != account_id:
                raise SourceError("source_account_mismatch")
            yield source
    else:
        raise SourceError("source_unavailable")


def _counts(result):
    counts = initial_counts()
    for name in ("inserted", "revised", "unchanged", "pages_processed"):
        counts[name] = getattr(result, name)
    for name in ('metadata_people', 'metadata_groups', 'names_scoped', 'names_missing'):
        counts[name] = getattr(result, name)
    for name in ('contacts_total', 'contacts_current', 'contacts_retained'):
        if (value := getattr(result, name)) is not None:
            counts[name] = value
    counts["conversations_total"] = result.total_conversations
    for name in ("completed", "failed", "incomplete"):
        attr = "successful_conversations" if name == "completed" else name + "_conversations"
        counts[name + "_conversations"] = len(getattr(result, attr))
    return counts


def _save_progress(conn, operation, owner, result, current):
    counts = _counts(result)
    with transaction(conn):
        changed = conn.execute("""UPDATE operations SET counts_json=?,updated_at=? WHERE account_id=? AND id=?
            AND worker_id=? AND state IN ('running','stop_requested')""",
            (json.dumps(counts), now(), operation.scope.account_id, operation.id, owner)).rowcount
        if changed:
            checkpoint = {"current_conversation_id": current, "source_result": result.model_dump(mode="json")}
            conn.execute("""UPDATE operation_items SET counts_json=?,gaps_json=?,checkpoint_json=?
                WHERE account_id=? AND operation_id=? AND item_id='source'""",
                (json.dumps(counts), json.dumps(sorted(set(result.gaps))), json.dumps(checkpoint),
                 operation.scope.account_id, operation.id))


def _owned(conn, operation, owner):
    row = conn.execute("SELECT state,generation,worker_id FROM operations WHERE account_id=? AND id=?",
                       (operation.scope.account_id, operation.id)).fetchone()
    return row and row[2] == owner and row[0] == "running" and row[1] == operation.generation


def _stop(conn, operation, owner):
    with transaction(conn):
        row = conn.execute("SELECT state,generation,worker_id FROM operations WHERE account_id=? AND id=?",
                           (operation.scope.account_id, operation.id)).fetchone()
        if row and row[2] == owner and row[0] in {"running", "stop_requested"}:
            generation = max(row[1], operation.generation + 1)
            error = None if row[0] == "stop_requested" else "operation_interrupted"
            conn.execute("""UPDATE operations SET state='stopped',generation=?,worker_id=NULL,error_code=?,updated_at=?
                            WHERE account_id=? AND id=?""", (generation, error, now(), operation.scope.account_id, operation.id))
            conn.execute("""UPDATE operation_items SET state='stopped',generation=?,error_code='user_stopped'
                            WHERE account_id=? AND operation_id=? AND state IN ('queued','running')""",
                         (generation, operation.scope.account_id, operation.id))


def _fail_source(conn, operation, owner, code, gaps):
    with transaction(conn):
        if not _owned(conn, operation, owner):
            return False
        conn.execute("""UPDATE operations SET state='failed',phase='source',remaining=1,error_code=?,worker_id=NULL,
                        updated_at=? WHERE account_id=? AND id=?""", (code, now(), operation.scope.account_id, operation.id))
        conn.execute("""UPDATE operation_items SET state='failed',error_code=?,gaps_json=?
                        WHERE account_id=? AND operation_id=? AND item_id='source'""",
                     (code, json.dumps(sorted(set(gaps))), operation.scope.account_id, operation.id))
    return True


def _complete_source(conn, operation, owner, result):
    with transaction(conn):
        if not _owned(conn, operation, owner):
            return False
        targets = []
        if operation.action == "sync_and_organize":
            targets = conn.execute("""SELECT c.contact_id,c.role_version FROM contacts c
                WHERE c.account_id=? AND c.role='merchant' AND c.is_self=0 AND c.identity_state='active'
                AND (? IS NULL OR c.contact_id=?) AND EXISTS (
                    SELECT 1 FROM messages m WHERE m.account_id=c.account_id AND (m.sender_id=c.contact_id OR EXISTS(
                        SELECT 1 FROM members s WHERE s.account_id=c.account_id AND s.contact_id=c.contact_id
                        AND s.conversation_id=m.conversation_id))) ORDER BY c.contact_id""",
                (operation.scope.account_id, operation.scope.contact_id, operation.scope.contact_id)).fetchall()
        counts = _counts(result)
        counts["analysis_required"] = len(targets)
        conn.execute("""UPDATE operation_items SET state='succeeded',error_code=NULL,gaps_json='[]',counts_json=?
                        WHERE account_id=? AND operation_id=? AND item_id='source'""",
                     (json.dumps(_counts(result)), operation.scope.account_id, operation.id))
        for target in targets:
            conn.execute("""INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,state,phase,
                            generation,role_version,error_code) VALUES (?,?,?,?,'failed','analysis',?,?,'capability_not_ready')""",
                         (operation.scope.account_id, operation.id, "analysis:" + target[0], target[0], operation.generation, target[1]))
        conn.execute("""UPDATE operations SET state=?,phase=?,remaining=?,counts_json=?,error_code=?,worker_id=NULL,
                        updated_at=? WHERE account_id=? AND id=?""",
                     ("failed" if targets else "succeeded", "analysis" if targets else "completed", len(targets),
                      json.dumps(counts), "capability_not_ready" if targets else None, now(), operation.scope.account_id, operation.id))
    return True


async def run_next(conn, services, *, account_id=None, on_claim=None):
    if account_id is None and services.source is not None:
        account_id = services.source.account_id
    claimed = _claim(conn, account_id)
    if claimed is None:
        return None
    operation, owner, encoded_options = claimed
    try:
        if on_claim:
            on_claim(operation)
        try:
            options = SyncOptions.model_validate_json(encoded_options)
        except ValidationError:
            _fail_source(conn, operation, owner, "invalid_operation_request", ["invalid_operation_request"])
            return get_operation(conn, operation.scope.account_id, operation.id)
        async with _source(services, operation.scope.account_id) as source:
            if operation.action == 'refresh_contacts':
                refresh = getattr(source, 'refresh_metadata', None)
                if not callable(refresh):
                    raise SourceError('source_metadata_refresh_unsupported')
                await refresh()
            result = await sync_scope(conn, source, operation.scope,
                CancellationToken(operation_id=operation.id, generation=operation.generation),
                **options.model_dump(), metadata_only=operation.action == 'refresh_contacts',
                on_progress=lambda value, target: _save_progress(conn, operation, owner, value, target))
        _save_progress(conn, operation, owner, result, None)
        if result.stopped:
            _stop(conn, operation, owner)
        elif result.gaps:
            unavailable = {"source_unavailable", "source_unreachable", "source_timeout", "source_not_ready",
                           "source_authentication_failed", "source_server_error", "source_account_mismatch"}
            code = "source_unavailable" if unavailable.intersection(result.gaps) else "source_incomplete"
            if not _fail_source(conn, operation, owner, code, result.gaps):
                _stop(conn, operation, owner)
        elif not _complete_source(conn, operation, owner, result):
            _stop(conn, operation, owner)
    except asyncio.CancelledError:
        _stop(conn, operation, owner)
    except SourceError as error:
        if not _fail_source(conn, operation, owner, "source_unavailable", [str(error)]):
            _stop(conn, operation, owner)
    except Exception:
        if not _fail_source(conn, operation, owner, "source_unavailable", ["source_unavailable"]):
            _stop(conn, operation, owner)
    return get_operation(conn, operation.scope.account_id, operation.id)


def _process_alive(owner):
    try:
        pid = int(owner.split(":", 1)[0])
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (ValueError, AttributeError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def recover_orphans(conn, account_id):
    with transaction(conn):
        rows = conn.execute("SELECT id,worker_id FROM operations WHERE account_id=? AND state IN ('running','stop_requested')",
                            (account_id,)).fetchall()
        for row in rows:
            if _process_alive(row[1]):
                continue
            conn.execute("""UPDATE operations SET state='stopped',generation=generation+1,worker_id=NULL,
                            error_code='operation_interrupted',updated_at=? WHERE account_id=? AND id=?""",
                         (now(), account_id, row[0]))
            conn.execute("""UPDATE operation_items SET state='stopped',generation=generation+1,error_code='operation_interrupted'
                            WHERE account_id=? AND operation_id=? AND state IN ('queued','running')""", (account_id, row[0]))


class WorkerRuntime:
    def __init__(self, database_path, services, account_resolver):
        self.database_path, self.services, self.account_resolver = database_path, services, account_resolver
        self.wake = asyncio.Event()
        self.closed = False
        self.active_id = None
        self.active_task = None
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._loop())

    def stop_operation(self, operation_id):
        if self.active_id == operation_id and self.active_task is not None:
            self.active_task.cancel()
        self.wake.set()

    async def close(self):
        self.closed = True
        if self.active_task is not None:
            self.active_task.cancel()
        self.wake.set()
        if self.task is not None:
            await self.task

    async def _loop(self):
        from ..accounts import AccountError
        while not self.closed:
            completed = None
            try:
                with closing(open_existing_db(self.database_path)) as conn:
                    account_id = self.account_resolver(conn)
                    recover_orphans(conn, account_id)
                    self.active_task = asyncio.create_task(run_next(conn, self.services, account_id=account_id,
                        on_claim=lambda operation: setattr(self, "active_id", operation.id)))
                    completed = await self.active_task
            except AccountError:
                pass
            except Exception:
                logging.getLogger(__name__).error("worker_unavailable")
            finally:
                self.active_id = self.active_task = None
            if self.closed:
                break
            if completed is not None:
                continue
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), 0.25)
            except TimeoutError:
                pass
