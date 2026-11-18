"""Explicit impact of source issues, separate from transport/control state."""
from typing import Literal
from pydantic import BaseModel,Field

class OperationIssue(BaseModel):
    code:str
    field_path:str|None=None
    stage:Literal['connection','metadata','messages','context','model','publication']
    severity:Literal['warning','blocker']
    scope:Literal['operation','contact','conversation']
    contact_id:str|None=None
    conversation_id:str|None=None
    suggested_action:Literal['retry_sync','open_model_settings','review_contact','none']='none'

class ContactCoverage(BaseModel):
    contact_id:str
    required_conversation_ids:list[str]=Field(default_factory=list)
    completed_conversation_ids:list[str]=Field(default_factory=list)
    failed_conversation_ids:list[str]=Field(default_factory=list)
    can_analyze:bool=False
    issues:list[OperationIssue]=Field(default_factory=list)

class SyncAssessment(BaseModel):
    global_blocked:bool=False
    contacts:dict[str,ContactCoverage]=Field(default_factory=dict)
    issues:list[OperationIssue]=Field(default_factory=list)

NUMBERLESS_MESSAGE = 'source_message_id_unavailable'

WARNINGS={'source_group_membership_unverified','source_name_read_failed','source_group_members_unreadable','source_group_members_unavailable'}
GLOBAL={'source_account_mismatch','source_changed_during_sync','source_metadata_changed','archive_write_failed','source_metadata_refresh_failed','source_metadata_refresh_timeout','source_contract_invalid','source_authentication_failed'}
LOCAL={'source_message_id_unavailable','source_timeout','source_unreachable','source_page_limit_reached','source_shards_unavailable','source_rows_skipped','message_sender_conflict','message_sender_missing','message_sender_invalid','message_contract_invalid','source_conversation_unavailable','source_empty_page_with_more','source_cursor_no_progress','source_page_no_progress'}

def assess_sync(conn,account_id,contact_ids,result):
    from ..contacts.conversations import resolve_contact_conversations
    from .contracts import ContactKey
    failed=set(result.failed_conversations)|set(result.incomplete_conversations)|set(result.missing_conversations)
    assessment=SyncAssessment()
    for code in result.gaps:
        warning=code in WARNINGS
        local=code in LOCAL and bool(failed)
        partial_warning = local and code == NUMBERLESS_MESSAGE
        issue=OperationIssue(code=code,stage='metadata' if warning or 'metadata' in code else 'messages',severity='warning' if warning or partial_warning else 'blocker',scope='operation',suggested_action='none' if warning else 'retry_sync')
        if local:
            for room in sorted(failed):
                if code in result.conversation_gaps.get(room,result.gaps):
                    assessment.issues.append(issue.model_copy(update={'scope':'conversation','conversation_id':room}))
        else:assessment.issues.append(issue)
        if not warning and not local:assessment.global_blocked=True
    for contact in sorted(contact_ids):
        required=resolve_contact_conversations(conn,ContactKey(account_id=account_id,contact_id=contact))
        complete=set(result.successful_conversations)&required
        missing=required-complete
        issues = [
            issue for issue in assessment.issues
            if assessment.global_blocked
            or (issue.severity == 'warning' and issue.conversation_id is None)
        ]
        blockers = set()
        for room in sorted(required):
            stored = {row[0] for row in conn.execute(
                'SELECT DISTINCT code FROM source_issues WHERE account_id=? AND conversation_id=? AND resolved=0',
                (account_id, room),
            )}
            if stored:
                missing.add(room)
            if room not in missing:
                continue
            current = set(result.conversation_gaps.get(room, ()))
            if room in failed and room not in result.conversation_gaps:
                current.update(set(result.gaps) & (LOCAL - {NUMBERLESS_MESSAGE}))
            if room in result.missing_conversations:
                current.add('source_conversation_unavailable')
            elif room not in complete and not current:
                current.add('source_not_complete')
            codes = current | stored
            if codes != {NUMBERLESS_MESSAGE} or room in result.incomplete_conversations:
                blockers.add(room)
            for code in sorted(codes):
                issues.append(OperationIssue(
                    code=code, stage='messages',
                    severity='warning' if code == NUMBERLESS_MESSAGE else 'blocker',
                    scope='conversation', contact_id=contact, conversation_id=room,
                    suggested_action='retry_sync',
                ))
        complete -= missing
        assessment.contacts[contact] = ContactCoverage(
            contact_id=contact, required_conversation_ids=sorted(required),
            completed_conversation_ids=sorted(complete), failed_conversation_ids=sorted(missing),
            can_analyze=bool(required) and not blockers and not assessment.global_blocked,
            issues=issues,
        )
    return assessment
