"""Account-owned source and analysis worker; publication rejects stale results."""

import asyncio
from contextlib import asynccontextmanager, closing
import json
import os
import sqlite3
from uuid import uuid4

from pydantic import ValidationError

from .contracts import CancellationToken, SyncOptions
from .service import get_operation, initial_counts, now
from ..source.adapter import SourceError
from ..source.coverage import assess_sync
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


def _fail_analysis(conn,operation,owner,code):
    with transaction(conn):
        if not _owned(conn,operation,owner):return False
        conn.execute("UPDATE operations SET state='failed',phase='analysis',error_code=?,worker_id=NULL,remaining=MAX(remaining,1),updated_at=? WHERE account_id=? AND id=?",(code,now(),operation.scope.account_id,operation.id))
        conn.execute("UPDATE operation_items SET state='failed',error_code=? WHERE account_id=? AND operation_id=? AND phase='analysis' AND state IN ('queued','running')",(code,operation.scope.account_id,operation.id))
    return True


def _complete_source(conn, operation, owner, result, *, ready=False, error_code="capability_not_ready"):
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
        from ..contacts.scope import decisions
        included=decisions(conn,operation.scope.account_id)
        targets=[target for target in targets if included[target['contact_id']].included]
        from ..source.coverage import assess_sync,OperationIssue
        from .reports import OperationReport,ContactOutcome,save_report,load_report
        pending_identity=set()
        if not ready and operation.action=='sync_and_organize':
            unknown={r[0] for r in conn.execute("SELECT contact_id FROM contacts WHERE account_id=? AND role='unknown' AND is_self=0 AND identity_state='active'",(operation.scope.account_id,))}
            pending_identity={c for c,d in included.items() if c in unknown and d.included and d.provisional and operation.scope.contact_id in (None,c)}
        assessment=assess_sync(conn,operation.scope.account_id,{t['contact_id'] for t in targets}|pending_identity,result)
        missing={room for c in assessment.contacts.values() for room in c.failed_conversation_ids} - set(result.failed_conversations) - set(result.incomplete_conversations) - set(result.missing_conversations) - set(result.successful_conversations)
        if missing:
            result.total_conversations+=len(missing)
            result.missing_conversations.extend(sorted(missing))
            result.gaps.append('source_conversation_unavailable')
            for coverage in assessment.contacts.values():
                coverage.issues=[issue.model_copy(update={'code':'source_conversation_unavailable'}) if issue.conversation_id in missing and issue.code=='source_not_complete' else issue for issue in coverage.issues]
            for room in sorted(missing):
                assessment.issues.append(OperationIssue(code='source_conversation_unavailable',stage='messages',severity='blocker',scope='conversation',conversation_id=room,suggested_action='retry_sync'))
        report=OperationReport(scope_label=operation.contact_name_snapshot or '全部范围',started_at=operation.updated_at,source_outcome='completed',issues=assessment.issues,
            contacts=[ContactOutcome(**c.model_dump(),reason=None if c.can_analyze else 'source_not_complete') for c in assessment.contacts.values()])
        for outcome in report.contacts:
            if outcome.contact_id in pending_identity:
                outcome.analysis_outcome='failed' if outcome.can_analyze else 'not_started'
                outcome.reason=error_code if outcome.can_analyze else 'source_not_complete'
                if outcome.can_analyze:outcome.issues.append(OperationIssue(code=error_code,stage='model',severity='blocker',scope='contact',contact_id=outcome.contact_id,suggested_action='open_model_settings'))
        pending_model=any(c.contact_id in pending_identity and c.can_analyze for c in report.contacts)
        if operation.scope.contact_id and not report.contacts:
            person=conn.execute('SELECT role FROM contacts WHERE account_id=? AND contact_id=?',(operation.scope.account_id,operation.scope.contact_id)).fetchone()
            report.contacts.append(ContactOutcome(contact_id=operation.scope.contact_id,reason='identity_pending' if person and person[0]=='unknown' else 'role_not_merchant' if person and person[0]!='merchant' else 'no_material',analysis_outcome='not_applicable'))
        previous=load_report(conn,operation.scope.account_id,operation.id)
        if previous:
            report.contacts.extend(c for c in previous.contacts if c.contact_id not in assessment.contacts)
            report.issues.extend(previous.issues)
        names={r['contact_id']:r['name'] for r in conn.execute("SELECT contact_id,COALESCE(NULLIF(remark,''),NULLIF(nickname,''),contact_id) AS name FROM contacts WHERE account_id=?",(operation.scope.account_id,))}
        for c in report.contacts:c.name_snapshot=names.get(c.contact_id)
        save_report(conn,operation.scope.account_id,operation.id,report)
        blocked=[t for t in targets if not assessment.contacts[t['contact_id']].can_analyze]
        targets=[t for t in targets if assessment.contacts[t['contact_id']].can_analyze]
        for target in blocked:
            conn.execute("INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,state,phase,generation,role_version,error_code) VALUES(?,?,?,?,'failed','analysis',?,?,?)",(operation.scope.account_id,operation.id,'analysis:'+target[0],target[0],operation.generation,target[1],'source_not_complete'))
        counts = _counts(result)
        counts["analysis_required"] = len(targets)+len(blocked)
        counts.update(analysis_completed=0,analysis_skipped=0,analysis_failed=len(targets) if not ready else 0,analysis_incomplete=0)
        conn.execute("""UPDATE operation_items SET state=?,error_code=NULL,gaps_json=?,counts_json=?
                        WHERE account_id=? AND operation_id=? AND item_id='source'""",
                     ('failed' if result.failed_conversations or result.incomplete_conversations or result.missing_conversations else 'succeeded',json.dumps(result.gaps),json.dumps(_counts(result)), operation.scope.account_id, operation.id))
        for target in targets:
            conn.execute("""INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,state,phase,
                            generation,role_version,error_code) VALUES (?,?,?,?,?,'analysis',?,?,?)""",
                         (operation.scope.account_id, operation.id, "analysis:" + target[0], target[0], 'queued' if ready else 'failed', operation.generation, target[1],None if ready else error_code))
        conn.execute("""UPDATE operations SET state=?,phase=?,remaining=?,counts_json=?,error_code=?,worker_id=NULL,
                        updated_at=? WHERE account_id=? AND id=?""",
                     ("running" if ready and targets else "failed" if targets or pending_model else "succeeded", "analysis" if targets or pending_model else "completed", len(targets),
                      json.dumps(counts), error_code if (targets or pending_model) and not ready else None, now(), operation.scope.account_id, operation.id))
        if ready and targets:conn.execute('UPDATE operations SET worker_id=? WHERE account_id=? AND id=?',(owner,operation.scope.account_id,operation.id))
    return [row[0] for row in targets]


async def run_next(conn, services, *, account_id=None, on_claim=None):
    if account_id is None and services.source is not None:
        account_id = services.source.account_id
    claimed = _claim(conn, account_id)
    if claimed is None:
        return None
    operation, owner, encoded_options = claimed
    runtime=None;runtime_error='capability_not_ready'
    if operation.action=='sync_and_organize' and services.analysis_factory is not None:
        from ..model.contracts import ModelCallError
        try:runtime=services.analysis_factory(conn,operation.scope.account_id)
        except ModelCallError as error:runtime_error=error.code
        except Exception:runtime_error='model_config_invalid'
    try:
        if on_claim:
            on_claim(operation)
        try:
            options = SyncOptions.model_validate_json(encoded_options)
        except ValidationError:
            _fail_source(conn, operation, owner, "invalid_operation_request", ["invalid_operation_request"])
            return get_operation(conn, operation.scope.account_id, operation.id)
        async with _source(services, operation.scope.account_id) as source:
            result = await sync_scope(conn, source, operation.scope,
                CancellationToken(operation_id=operation.id, generation=operation.generation),
                **options.model_dump(), metadata_only=operation.action == 'refresh_contacts',
                on_progress=lambda value, target: _save_progress(conn, operation, owner, value, target))
        from ..contacts.activity import refresh_activity
        with transaction(conn):refresh_activity(conn,operation.scope.account_id)
        _save_progress(conn, operation, owner, result, None)
        if result.stopped:
            _stop(conn, operation, owner)
        elif (result.gaps and operation.action != 'sync_and_organize') or assess_sync(conn,operation.scope.account_id,set(),result).global_blocked:
            unavailable = {"source_unavailable", "source_unreachable", "source_timeout", "source_not_ready",
                           "source_authentication_failed", "source_server_error", "source_account_mismatch"}
            code = "source_unavailable" if unavailable.intersection(result.gaps) else "source_incomplete"
            if not _fail_source(conn, operation, owner, code, result.gaps):
                _stop(conn, operation, owner)
        else:
            if runtime is not None:
                from ..analysis.runner import discover,analyze
                with transaction(conn):
                    if _owned(conn,operation,owner):
                        conn.execute("UPDATE operation_items SET state='succeeded',error_code=NULL,gaps_json='[]' WHERE account_id=? AND operation_id=? AND item_id='source'",(operation.scope.account_id,operation.id))
                        conn.execute("UPDATE operations SET phase='analysis',updated_at=? WHERE account_id=? AND id=?",(now(),operation.scope.account_id,operation.id))
                async with runtime as session:
                    await discover(conn,operation,owner,session.discovery,sync_result=result)
                    targets=_complete_source(conn,operation,owner,result,ready=True)
                    if targets:await analyze(conn,operation,owner,session,targets)
                    elif targets is False:_stop(conn,operation,owner)
            else:
                targets=_complete_source(conn,operation,owner,result,error_code=runtime_error)
                if targets is False:_stop(conn,operation,owner)
    except asyncio.CancelledError:
        _stop(conn, operation, owner)
    except SourceError as error:
        if not _fail_source(conn, operation, owner, "source_unavailable", [str(error)]):
            _stop(conn, operation, owner)
    except Exception:
        current=get_operation(conn,operation.scope.account_id,operation.id)
        if current.phase=='analysis':
            if not _fail_analysis(conn,operation,owner,'analysis_failed'):_stop(conn,operation,owner)
        elif not _fail_source(conn, operation, owner, "source_unavailable", ["source_unavailable"]):
            _stop(conn, operation, owner)
    from .reports import finalize_report
    with transaction(conn):finalize_report(conn,operation.scope.account_id,operation.id)
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
