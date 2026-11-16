"""Bounded serial analysis for already-synced contacts; publication rechecks inputs."""
import asyncio
from datetime import datetime,timezone
import json
from ..source.contracts import ContactKey
from ..source.repository import transaction
from ..context.builder import build_snapshot
from ..context.reader import ContextReader
from ..model.contracts import ModelCallError
from ..profiles.publisher import publish
from ..operations.contracts import CancellationToken
from ..operations.service import now


def unchanged(conn,snapshot):
    previous=conn.execute('''SELECT s.manifest_json,s.payload_json FROM profile_heads h JOIN profile_versions p
        ON p.account_id=h.account_id AND p.contact_id=h.contact_id AND p.version=h.version
        JOIN snapshots s ON s.account_id=p.account_id AND s.snapshot_id=p.snapshot_id
        WHERE h.account_id=? AND h.contact_id=?''',(snapshot.key.account_id,snapshot.key.contact_id)).fetchone()
    if not previous:return False
    manifest=json.loads(previous['manifest_json'])
    for field in ('role_version','scope_version','manual_version','versions','gaps','coverage'):
        if manifest.get(field)!=json.loads(snapshot.model_dump_json()).get(field):return False
    current=ContextReader(conn,snapshot)
    payload=json.loads(previous['payload_json'])
    return payload['messages']==current.messages() and payload['actors']==current.actors() and payload['conversations']==current.conversations() and payload.get('manual',{'fields':{},'notes':{}})==current.manual()


async def analyze(conn,operation,owner,session,targets):
    from ..operations.worker import _owned,_stop
    counts=dict(operation.counts)
    saved=conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',(operation.scope.account_id,operation.id)).fetchone()
    counts.update(json.loads(saved[0]))
    counts.update(analysis_completed=0,analysis_skipped=0,analysis_failed=0,analysis_incomplete=0)
    token=CancellationToken(operation_id=operation.id,generation=operation.generation)
    first_error=None
    for contact in targets:
        if not _owned(conn,operation,owner):_stop(conn,operation,owner);return
        code=None;issues=[];skipped=False;incomplete=False
        with transaction(conn):conn.execute("UPDATE operation_items SET state='running' WHERE account_id=? AND operation_id=? AND item_id=?",(operation.scope.account_id,operation.id,'analysis:'+contact))
        try:
            from ..operations.reports import load_report
            from ..context.contracts import ContextCoverage
            report=load_report(conn,operation.scope.account_id,operation.id)
            item=next((c for c in report.contacts if c.contact_id==contact),None) if report else None
            if report and (not item or not item.can_analyze):raise ModelCallError('source_not_complete')
            coverage=ContextCoverage(required_conversation_ids=tuple(item.required_conversation_ids),completed_conversation_ids=tuple(item.completed_conversation_ids),warning_codes=tuple(sorted({i.code for i in item.issues if i.severity=='warning'}))) if item else None
            snapshot=build_snapshot(conn,ContactKey(account_id=operation.scope.account_id,contact_id=contact),datetime.now(timezone.utc),coverage=coverage,versions={'template':'profile-v1','strategy':getattr(session.workflow,'strategy_version','workflow-v1'),'output_schema':'1','model_config':session.config.version})
            if coverage and (set(coverage.required_conversation_ids)!=set(ContextReader(conn,snapshot).conversations()) or any(gap.split(':',1)[0] in {'source_not_complete','source_gap','source_issue','message_time_invalid','message_author_unverified'} for gap in snapshot.gaps)):
                raise ModelCallError('source_not_complete')
            if unchanged(conn,snapshot):
                skipped=True
                previous=conn.execute('SELECT p.issues_json FROM profile_heads h JOIN profile_versions p ON p.account_id=h.account_id AND p.contact_id=h.contact_id AND p.version=h.version WHERE h.account_id=? AND h.contact_id=?',(operation.scope.account_id,contact)).fetchone()
                issues=sorted(set(snapshot.gaps)|set(json.loads(previous[0]) if previous else []))
            else:
                candidate=await session.workflow.run(snapshot,None,token)
                result=publish(conn,snapshot,candidate,token)
                issues=result.issues
                if result.reason:raise ModelCallError(result.reason)
                incomplete=not result.complete;issues=result.issues
        except asyncio.CancelledError:raise
        except ModelCallError as error:code=error.code
        except Exception:code='analysis_failed'
        if not _owned(conn,operation,owner):_stop(conn,operation,owner);return
        # The history workflow persists progress while running. Do not overwrite
        # these live counters with the runner's pre-call copy at terminalization.
        live=conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',(operation.scope.account_id,operation.id)).fetchone()
        counts.update(json.loads(live[0]))
        if code:counts['analysis_failed']+=1;first_error=first_error or code
        elif skipped:counts['analysis_skipped']+=1
        else:counts['analysis_completed']+=1;counts['analysis_incomplete']+=int(incomplete)
        with transaction(conn):
            if not _owned(conn,operation,owner):_stop(conn,operation,owner);return
            conn.execute('''UPDATE operation_items SET state=?,error_code=?,gaps_json=?,counts_json=? WHERE account_id=? AND operation_id=? AND item_id=?''',
                ('failed' if code else 'succeeded',code or ('analysis_incomplete' if incomplete else None),json.dumps(issues),json.dumps({'skipped':int(skipped)}),operation.scope.account_id,operation.id,'analysis:'+contact))
            conn.execute('UPDATE operations SET counts_json=?,remaining=?,updated_at=? WHERE account_id=? AND id=?',
                (json.dumps(counts),len(targets)-counts['analysis_completed']-counts['analysis_skipped'],now(),operation.scope.account_id,operation.id))
    with transaction(conn):
        if not _owned(conn,operation,owner):_stop(conn,operation,owner);return
        conn.execute('''UPDATE operations SET state=?,phase=?,error_code=?,worker_id=NULL,updated_at=? WHERE account_id=? AND id=?''',
            ('failed' if first_error else 'succeeded','analysis' if first_error else 'completed',first_error or ('analysis_incomplete' if counts['analysis_incomplete'] else None),now(),operation.scope.account_id,operation.id))


async def discover(conn,operation,owner,strategy,*,sync_result=None):
    from ..operations.worker import _owned
    from ..contacts.scope import decisions
    from ..discovery.context import build_discovery_snapshot
    from ..discovery.repository import publish_discovery
    token=CancellationToken(operation_id=operation.id,generation=operation.generation)
    unknown={row[0] for row in conn.execute("SELECT contact_id FROM contacts WHERE account_id=? AND role='unknown'",(operation.scope.account_id,))}
    candidates=[contact for contact,decision in decisions(conn,operation.scope.account_id).items() if contact in unknown and decision.provisional and operation.scope.contact_id in (None,contact)]
    for contact in candidates:
        if not _owned(conn,operation,owner):return
        from ..source.coverage import assess_sync
        from ..operations.reports import OperationReport,ContactOutcome,load_report,save_report
        from ..source.coverage import OperationIssue
        report=load_report(conn,operation.scope.account_id,operation.id) or OperationReport(scope_label=operation.contact_name_snapshot or '全部范围',source_outcome='completed')
        coverage=assess_sync(conn,operation.scope.account_id,{contact},sync_result).contacts[contact] if sync_result is not None else None
        if coverage and not coverage.can_analyze:
            report.contacts.append(ContactOutcome(**coverage.model_dump(),analysis_outcome='failed',reason='source_not_complete'))
            with transaction(conn):save_report(conn,operation.scope.account_id,operation.id,report)
            continue
        try:
            snapshot=build_discovery_snapshot(conn,ContactKey(account_id=operation.scope.account_id,contact_id=contact),datetime.now(timezone.utc),versions={'model_config':strategy.gateway.config.version})
            result=await strategy.classify(snapshot,token)
            publish_discovery(conn,snapshot,result,token)
        except asyncio.CancelledError:raise
        except Exception:
            report.contacts.append(ContactOutcome(contact_id=contact,analysis_outcome='failed',reason='classification_failed',issues=[OperationIssue(code='classification_failed',stage='model',severity='blocker',scope='contact',contact_id=contact,suggested_action='open_model_settings')]))
            with transaction(conn):save_report(conn,operation.scope.account_id,operation.id,report)
