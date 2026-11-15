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
    for field in ('role_version','scope_version','manual_version','versions','gaps'):
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
            snapshot=build_snapshot(conn,ContactKey(account_id=operation.scope.account_id,contact_id=contact),datetime.now(timezone.utc),versions={'template':'profile-v1','strategy':'workflow-v1','output_schema':'1','model_config':session.config.version})
            if unchanged(conn,snapshot):skipped=True
            else:
                candidate=await session.workflow.run(snapshot,None,token)
                result=publish(conn,snapshot,candidate,token)
                if result.reason:raise ModelCallError(result.reason)
                incomplete=not result.complete;issues=result.issues
        except asyncio.CancelledError:raise
        except ModelCallError as error:code=error.code
        except Exception:code='analysis_failed'
        if not _owned(conn,operation,owner):_stop(conn,operation,owner);return
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


async def discover(conn,operation,owner,strategy):
    from ..operations.worker import _owned
    from ..contacts.scope import decisions
    from ..discovery.context import build_discovery_snapshot
    from ..discovery.repository import publish_discovery
    token=CancellationToken(operation_id=operation.id,generation=operation.generation)
    unknown={row[0] for row in conn.execute("SELECT contact_id FROM contacts WHERE account_id=? AND role='unknown'",(operation.scope.account_id,))}
    candidates=[contact for contact,decision in decisions(conn,operation.scope.account_id).items() if contact in unknown and decision.provisional and operation.scope.contact_id in (None,contact)]
    for contact in candidates:
        if not _owned(conn,operation,owner):return
        try:
            snapshot=build_discovery_snapshot(conn,ContactKey(account_id=operation.scope.account_id,contact_id=contact),datetime.now(timezone.utc),versions={'model_config':strategy.gateway.config.version})
            result=await strategy.classify(snapshot,token)
            publish_discovery(conn,snapshot,result,token)
        except asyncio.CancelledError:raise
        except Exception:pass  # Unverified leads remain provisional, never silently excluded.
