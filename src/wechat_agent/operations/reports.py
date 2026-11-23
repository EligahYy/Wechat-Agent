"""Account-scoped durable execution facts; no provider bodies or message text."""
from typing import Literal
from pydantic import BaseModel,Field
from ..source.coverage import OperationIssue,ContactCoverage,WARNINGS,NUMBERLESS_MESSAGE

class ContactOutcome(ContactCoverage):
    name_snapshot:str|None=None
    reason:str|None=None
    analysis_outcome:Literal['not_started','running','updated','unchanged','partial','failed','not_applicable','stopped']='not_started'

class OperationReport(BaseModel):
    version:Literal[1]=1
    scope_label:str
    source_outcome:Literal['not_started','running','completed','partial','failed','stopped']='not_started'
    analysis_outcome:Literal['not_started','running','updated','unchanged','partial','failed','not_applicable','stopped']='not_started'
    started_at:str|None=None
    finished_at:str|None=None
    contacts:list[ContactOutcome]=Field(default_factory=list)
    issues:list[OperationIssue]=Field(default_factory=list)

def load_report(conn,account_id,operation_id):
    row=conn.execute('SELECT report_json FROM operation_reports WHERE account_id=? AND operation_id=?',(account_id,operation_id)).fetchone()
    return OperationReport.model_validate_json(row[0]) if row else None

def save_report(conn,account_id,operation_id,report):
    if not conn.execute('SELECT 1 FROM operations WHERE account_id=? AND id=?',(account_id,operation_id)).fetchone():
        raise ValueError('operation_not_found')
    report=OperationReport.model_validate(report)
    conn.execute('INSERT INTO operation_reports VALUES(?,?,?) ON CONFLICT(account_id,operation_id) DO UPDATE SET report_json=excluded.report_json',(account_id,operation_id,report.model_dump_json()))

def analysis_issue(raw,contact):
    # Model gap strings may contain customer text: persist fixed codes only.
    import re
    from ..profiles.contracts import Goods,Logistics
    path=raw.split(':',1)[0]
    fields={*(f'goods.{n}' for n in Goods.model_fields),*(f'logistics.{n}' for n in Logistics.model_fields),'communication.summary','communication.tags','communication.last_business_at'}
    coverage={'history_complete_unverified','attachment_not_processed','reply_unavailable'}
    if path in coverage:code,stage,field=path,'context',None
    elif path in fields:code,stage,field='profile_field_invalid','publication',path
    elif re.fullmatch(r'shipments\.\d+(?:\.(?:goods|logistics))?',path):code,stage,field='shipment_field_invalid','publication',path
    elif path in {'shipment_match_ambiguous','shipment_match_conflict','shipment_outside_contact','shipment_target_conflict'}:code,stage,field='shipment_field_invalid','publication',None
    else:code,stage,field='analysis_review_required','publication',None
    return OperationIssue(code=code,field_path=field,stage=stage,severity='warning',scope='contact',contact_id=contact)

def suggested_action(code):
    if code in {'model_timeout','model_temporary_error','model_retry_limit','rate_limited','retry_after_exceeds_deadline','model_retry_cooling_down'}:return 'retry_sync'
    if code in {'scope_excluded','scope_changed','contact_changed','retained_evidence_unavailable'}:return 'review_contact'
    if code in {'context_requires_chunking','history_merge_unit_too_large','context_reference_too_large','context_message_overhead_exceeded'}:return 'none'
    if code.startswith('model_') or code in {'capability_not_ready','authentication_failed','credential_unavailable','credential_store_unsupported','request_invalid'}:return 'open_model_settings'
    return 'retry_sync'

def finalize_report(conn,account_id,operation_id):
    from .service import get_operation
    operation=get_operation(conn,account_id,operation_id)
    report=operation.report or OperationReport(scope_label=operation.contact_name_snapshot or ('全部范围' if not operation.scope.contact_id else operation.scope.contact_id))
    source=next((i for i in operation.items if i.phase=='source'),None)
    if source:
        report.source_outcome={'succeeded':'completed','failed':'partial' if operation.counts.get('completed_conversations',0) else 'failed','stopped':'stopped','running':'running'}.get(source.state,'not_started')
        for code in source.gaps:
            if code=='source_sync_stopped':continue
            if not any(i.code==code for i in report.issues):
                report.issues.append(OperationIssue(code=code,stage='metadata' if 'metadata' in code else 'messages',severity='warning' if code in WARNINGS else 'blocker',scope='operation',suggested_action='retry_sync'))
    if source and source.state=='failed' and any(i.severity=='blocker' and i.scope=='operation' for i in report.issues):report.source_outcome='failed'
    items=[i for i in operation.items if i.phase=='analysis']
    contacts={c.contact_id:c for c in report.contacts}
    for item in items:
        outcome=contacts.setdefault(item.contact_id,ContactOutcome(contact_id=item.contact_id))
        outcome.reason=item.error_code
        verified_source_gaps = {
            f'{i.code}:{i.conversation_id}' for i in outcome.issues
            if i.code == NUMBERLESS_MESSAGE and i.conversation_id and i.severity == 'warning'
        }
        from ..profiles.issues import classify_issues
        optional_gaps = {i.detail for i in classify_issues(item.gaps) if i.severity == 'business_uncertainty'}
        normalized = [analysis_issue(gap, item.contact_id) for gap in item.gaps if gap not in verified_source_gaps | optional_gaps]
        for issue in normalized:
            if not any(i.code==issue.code and i.field_path==issue.field_path for i in outcome.issues):outcome.issues.append(issue)
        field_incomplete=item.error_code=='analysis_incomplete' and any(i.stage=='publication' for i in normalized)
        if item.error_code and item.error_code not in {'analysis_incomplete','user_stopped','cancelled','analysis_budget_paused','no_relevant_material'}:
            stage='publication' if item.error_code in {'manual_changed','material_changed','profile_changed','scope_changed','contact_changed','retained_evidence_unavailable','scope_excluded','participants_changed','snapshot_not_authorized'} else 'context' if item.error_code in {'source_not_complete','context_requires_chunking','context_fixed_overhead_exceeded','context_reference_too_large','context_message_overhead_exceeded','history_merge_unit_too_large','history_merge_incomplete','history_coverage_incomplete','chunk_source_outside_unit','merge_scope_invalid','checkpoint_invalid'} else 'model'
            issue=OperationIssue(code=item.error_code,stage=stage,severity='blocker',scope='contact',contact_id=item.contact_id,suggested_action=suggested_action(item.error_code))
            if not any(i.code==issue.code for i in outcome.issues):outcome.issues.append(issue)
        if item.state == 'succeeded' and any(i.code == NUMBERLESS_MESSAGE and i.severity == 'warning' for i in outcome.issues):
            outcome.analysis_outcome = 'unchanged' if item.counts.get('skipped') else 'partial'
            continue
        if item.error_code == 'no_relevant_material':
            outcome.analysis_outcome = 'not_applicable'
            continue
        outcome.analysis_outcome='not_started' if item.error_code=='source_not_complete' else 'failed' if item.state=='failed' else 'stopped' if item.state=='stopped' else 'unchanged' if item.counts.get('skipped') else 'partial' if item.state=='succeeded' and field_incomplete else 'updated' if item.state=='succeeded' else 'running'
    report.contacts=list(contacts.values())
    if any(c.failed_conversation_ids or c.reason=='source_not_complete' for c in report.contacts):report.source_outcome='partial'
    states={c.analysis_outcome for c in report.contacts}
    if operation.state=='stopped':report.analysis_outcome='stopped'
    elif operation.state=='failed' and operation.phase=='analysis' and not items and operation.error_code:report.analysis_outcome='failed'
    elif any(c.reason=='source_not_complete' for c in report.contacts):report.analysis_outcome='partial' if states & {'updated','unchanged','partial'} else 'not_started'
    elif states & {'failed'}:report.analysis_outcome='partial' if states & {'updated','unchanged','partial'} else 'failed'
    elif 'partial' in states:report.analysis_outcome='partial'
    elif 'running' in states:report.analysis_outcome='running'
    elif 'updated' in states:report.analysis_outcome='updated'
    elif 'unchanged' in states:report.analysis_outcome='unchanged'
    elif operation.state=='stopped':report.analysis_outcome='stopped'
    elif operation.source_state=='succeeded':report.analysis_outcome='not_applicable'
    else:report.analysis_outcome='not_started'
    report.finished_at=operation.updated_at if operation.state in {'succeeded','failed','stopped'} else None
    if operation.state=='failed' and operation.error_code and operation.error_code!='analysis_budget_paused' and operation.phase=='analysis' and not any(i.code==operation.error_code for i in [*report.issues,*[i for c in report.contacts for i in c.issues]]):
        report.issues.append(OperationIssue(code=operation.error_code,stage='model',severity='blocker',scope='operation',suggested_action=suggested_action(operation.error_code)))
    save_report(conn,account_id,operation_id,report)
    all_issues = [*report.issues, *(issue for contact in report.contacts for issue in contact.issues)]
    known_partial = (
        report.source_outcome == 'partial'
        and states & {'updated', 'unchanged', 'partial'}
        and any(i.code == NUMBERLESS_MESSAGE and i.severity == 'warning' for i in all_issues)
        and not any(i.severity == 'blocker' for i in all_issues)
    )
    if ('failed' in states or (report.source_outcome in {'partial','failed'} and not known_partial)) and operation.state=='succeeded':
        conn.execute("UPDATE operations SET state='failed',error_code='analysis_partial' WHERE account_id=? AND id=?",(account_id,operation_id))
    return report
