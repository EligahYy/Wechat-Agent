"""Atomic publication of validated candidates after rechecking mutable inputs."""
import json
from pydantic import BaseModel,Field
from .validator import validate_result
from .shipments import save_shipments
from .contracts import AnalysisResult,ShipmentCandidate
from ..context.reader import ContextReader
from ..context.contracts import SnapshotError
from ..contacts.scope import business_scope_allows_analysis
from ..source.repository import transaction,cancellation_requested
from ..source.coverage import NUMBERLESS_MESSAGE

class PublishResult(BaseModel):
    version:int|None=None
    complete:bool=False
    reason:str|None=None
    pending:bool=False
    issues:list[str]=Field(default_factory=list)


def check_inputs(conn,snapshot,cancellation):
    """Call under a transaction, both before model work and at publication."""
    account,contact=snapshot.key.account_id,snapshot.key.contact_id
    if cancellation_requested(conn,account,cancellation):return None,None,'cancelled'
    operation=conn.execute('SELECT contact_id,action FROM operations WHERE account_id=? AND id=?',(account,cancellation.operation_id)).fetchone()
    if not operation or operation['action']!='sync_and_organize' or operation['contact_id'] not in (None,contact):return None,None,'operation_scope_mismatch'
    try:reader=ContextReader(conn,snapshot)
    except (SnapshotError,ValueError):return None,None,'snapshot_not_authorized'
    person=conn.execute('SELECT * FROM contacts WHERE account_id=? AND contact_id=?',(account,contact)).fetchone()
    if not person or person['is_self'] or person['identity_state']!='active' or person['role']!='merchant' or person['role_version']!=snapshot.role_version:return None,None,'contact_changed'
    if not business_scope_allows_analysis(conn,snapshot.key):return None,None,'scope_excluded'
    override=conn.execute('SELECT version FROM business_scope_overrides WHERE account_id=? AND contact_id=?',(account,contact)).fetchone()
    if (override[0] if override else 0)!=snapshot.scope_version:return None,None,'scope_changed'
    head=conn.execute('SELECT * FROM profile_heads WHERE account_id=? AND contact_id=?',(account,contact)).fetchone()
    if (head['manual_version'] if head else 0)!=snapshot.manual_version:return None,None,'manual_changed'
    for actor,old in reader.actors().items():
        current=conn.execute('SELECT role_version,is_self,identity_state FROM contacts WHERE account_id=? AND contact_id=?',(account,actor)).fetchone()
        if not current or current['identity_state']!='active' or current['role_version']!=old['role_version'] or bool(current['is_self'])!=old['is_self']:return None,None,'participants_changed'
    for ref in snapshot.material_refs:
        current=conn.execute('SELECT revision FROM messages WHERE account_id=? AND message_id=?',(account,ref.message_id)).fetchone()
        if not current or current[0]!=ref.revision:return None,None,'material_changed'
    return reader,head,None


class RetentionError(Exception):
    pass

def publish(conn,snapshot,result,cancellation):
    try:return _publish(conn,snapshot,result,cancellation)
    except RetentionError:return PublishResult(reason='retained_evidence_unavailable')

def _publish(conn,snapshot,result,cancellation):
    with transaction(conn):
        reader,head,reason=check_inputs(conn,snapshot,cancellation)
        if reason:return PublishResult(reason=reason)
        account,contact=snapshot.key.account_id,snapshot.key.contact_id
        validated=validate_result(conn,snapshot,result)
        if validated.reason:return PublishResult(reason=validated.reason,issues=validated.issues)
        previous=conn.execute('SELECT * FROM profile_versions WHERE account_id=? AND snapshot_id=?',(account,snapshot.id)).fetchone()
        if previous:return PublishResult(version=previous['version'],complete=bool(previous['complete']),pending=bool(previous['pending']),issues=json.loads(previous['issues_json']))
        if (head['version'] if head else 0)!=snapshot.profile_version:return PublishResult(reason='profile_changed')
        candidate=validated.result;issues=list(validated.issues)
        if head and head['version']:
            old=AnalysisResult.model_validate_json(conn.execute('SELECT result_json FROM profile_versions WHERE account_id=? AND contact_id=? AND version=?',(account,contact,head['version'])).fetchone()[0])
            prior=validate_result(conn,snapshot,old)
            original_old=old
            old=prior.result
            if snapshot.coverage is not None:
                for group in ('goods','logistics'):
                    for name in type(getattr(candidate,group)).model_fields:
                        current=getattr(getattr(candidate,group),name)
                        previous=getattr(getattr(original_old,group),name)
                        if not current.value and previous.value:
                            retained=getattr(getattr(old,group),name) if old else None
                            if retained is None or not retained.value:
                                return PublishResult(reason='retained_evidence_unavailable')
                            setattr(getattr(candidate,group),name,retained)
                if not candidate.communication.summary.value and original_old.communication.summary.value:
                    if not old or not old.communication.summary.value:return PublishResult(reason='retained_evidence_unavailable')
                    candidate.communication=old.communication
            # Restore only prior fields still authorized by this input snapshot.
            for path in issues if old is not None else []:
                name=path.split(':')[0];parts=name.split('.')
                if len(parts)==2 and parts[0] in ('goods','logistics'):setattr(getattr(candidate,parts[0]),parts[1],getattr(getattr(old,parts[0]),parts[1]))
                if name=='communication.summary':candidate.communication=old.communication
        original=AnalysisResult.model_validate(result.model_dump() if isinstance(result,AnalysisResult) else result)
        indices={}
        for i,batch in enumerate(original.shipments):indices.setdefault(batch.candidate_key,i)
        def restore_batch(payload,batch):
            prior=validate_result(conn,snapshot,AnalysisResult(contact_id=contact,shipments=[ShipmentCandidate.model_validate_json(payload)]))
            previous_batch=ShipmentCandidate.model_validate_json(payload)
            if snapshot.coverage is not None:
                restored=prior.result.shipments[0] if prior.result and prior.result.shipments else None
                for group in ('goods','logistics'):
                    if not getattr(batch,group) and getattr(previous_batch,group):
                        if not restored or len(getattr(restored,group)) != len(getattr(previous_batch,group)):
                            raise RetentionError()
                        setattr(batch,group,getattr(restored,group))
            if prior.result and prior.result.shipments:
                old=prior.result.shipments[0]
                for group in ('goods','logistics'):
                    prefix=f'shipments.{indices[batch.candidate_key]}.{group}:'
                    if any(issue.startswith(prefix) for issue in issues):
                        # Untyped fact lists cannot safely be paired by array index.
                        facts=[fact for fact in [*getattr(batch,group),*getattr(old,group)] if fact.value]
                        setattr(batch,group,list({fact.model_dump_json():fact for fact in facts}.values()))
            return batch
        candidate.shipments,batch_issues=save_shipments(conn,snapshot.key,candidate.shipments,restore_batch);issues.extend(batch_issues)
        meaningful=any(getattr(getattr(candidate,group),name).value for group in ('goods','logistics') for name in type(getattr(candidate,group)).model_fields) or candidate.communication.summary.value
        if not candidate.shipments and not meaningful:return PublishResult(reason='empty_result',issues=issues)
        rooms={row[0] for row in conn.execute('''SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?
            UNION SELECT conversation_id FROM messages WHERE account_id=? AND sender_id=?''',(account,contact,account,contact))}
        refs={ref.message_id for ref in snapshot.material_refs}
        pending=any(row[0] not in refs for room in rooms for row in conn.execute('SELECT message_id FROM messages WHERE account_id=? AND conversation_id=?',(account,room)))
        # Source coverage notices come from the archive, never model output.
        model_gaps = {gap for gap in candidate.gaps if gap.partition(':')[0] != NUMBERLESS_MESSAGE}
        gaps=sorted(set(snapshot.gaps)|model_gaps|set(issues))
        complete=not gaps
        version=(head['version'] if head else 0)+1
        conn.execute('INSERT INTO profile_heads(account_id,contact_id,version) VALUES(?,?,?) ON CONFLICT(account_id,contact_id) DO UPDATE SET version=excluded.version',(account,contact,version))
        conn.execute('INSERT INTO profile_versions(account_id,contact_id,version,snapshot_id,candidate_json,result_json,issues_json,complete,pending) VALUES(?,?,?,?,?,?,?,?,?)',
            (account,contact,version,snapshot.id,result.model_dump_json() if isinstance(result,AnalysisResult) else json.dumps(result,ensure_ascii=False),candidate.model_dump_json(),json.dumps(gaps,ensure_ascii=False),int(complete),int(pending)))
        return PublishResult(version=version,complete=complete,pending=pending,issues=gaps)
