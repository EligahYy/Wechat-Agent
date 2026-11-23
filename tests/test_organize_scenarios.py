"""Replay coverage boundaries using the design's source-failure data."""
import pytest
from tests.organize_scenarios import load_cases
from tests.factories import seed_case
from wechat_agent.source.coverage import assess_sync
from wechat_agent.source.sync import SyncResult
from wechat_agent.source.contracts import ContactKey
from wechat_agent.contacts.conversations import resolve_contact_conversations

SOURCE_CASES=[c for c in load_cases() if 'global_failure' in c['given'] or 'room_failure' in c['given'] or 'unrelated_group_membership' in c['given']]

@pytest.mark.parametrize('case',SOURCE_CASES,ids=lambda c:c['id'])
def test_source_scenario_boundaries(db,case):
    seed_case(db)
    rooms=resolve_contact_conversations(db,ContactKey(account_id='acct-1',contact_id='merchant-a'))
    given=case['given'];result=SyncResult(successful_conversations=sorted(rooms))
    if 'global_failure' in given:
        result.gaps=[given['global_failure']]
    elif 'room_failure' in given:
        room='group-1';result.successful_conversations.remove(room)
        result.failed_conversations=[room];result.gaps=list(given['room_failure'].values())
    else:result.gaps=['source_group_membership_unverified']
    actual=assess_sync(db,'acct-1',{'merchant-a'},result)
    assert actual.contacts['merchant-a'].can_analyze == (not given.get('global_failure') and not given.get('room_failure'))
    assert actual.global_blocked == bool(given.get('global_failure'))


def test_design_inputs_are_unique_and_unknown_fields_are_not_ignored(tmp_path):
    import json
    cases=list(load_cases());assert len(cases)==45
    path=tmp_path/'bad.json';path.write_text(json.dumps({'version':1,'cases':[{'id':'bad','given':{'silently_ignored':True},'expect':{}}]}))
    with pytest.raises(ValueError,match='unknown_scenario_field'):list(load_cases(path))

@pytest.mark.asyncio
@pytest.mark.parametrize('case',list(load_cases()),ids=lambda c:c['id'])
async def test_complete_scenario_pipeline(db,case):
    from tests.organize_scenarios import run_scenario
    observed=await run_scenario(db,case)
    for field in ('source_outcome','analysis_outcome','model_calls','publish'):
        assert observed[field]==case['expect'][field],(case['id'],field,observed['operation'])

    expected=case['expect'].get('reason')
    op=observed['operation']
    if expected and op:
        codes={op.error_code}|{g for i in op.items for g in i.gaps}
        if op.report:
            codes.update(i.code for i in op.report.issues)
            codes.update(c.reason for c in op.report.contacts)
            codes.update(i.code for c in op.report.contacts for i in c.issues)
        aliases={'coverage_unverified':{'source_group_membership_unverified'},'scope_changed':{'scope_changed','scope_excluded'},'invalid_evidence':{'evidence_unverified','source_invalid'},'user_stopped':{'user_stopped','cancelled','source_sync_stopped'}}
        if expected=='legacy_reason_unavailable':assert op.report is None
        elif expected=='metadata_only':assert op.action=='refresh_contacts'
        elif expected=='user_stopped':assert op.state=='stopped'
        else:assert codes & aliases.get(expected,{expected}),(case['id'],expected,codes)

@pytest.mark.asyncio
async def test_retry_partial_batch_does_not_pay_for_already_unchanged_customer(db):
    from tests.organize_scenarios import run_scenario
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.worker import run_next
    case=next(c for c in load_cases() if c['id']=='mixed_account_batch')
    initial=await run_scenario(db,case)
    initial['given'].pop('room_failure')
    initial['calls'].clear()
    create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1'),'retry-batch')
    result=await run_next(db,initial['services'])
    assert len(initial['calls'])==1
    outcomes={c.contact_id:c.analysis_outcome for c in result.report.contacts}
    assert outcomes=={'merchant-a':'updated','merchant-b':'unchanged'}

@pytest.mark.asyncio
async def test_provisional_identity_needing_model_reports_unreviewed_budget(db):
    from tests.organize_scenarios import run_scenario
    case={'id':'provisional-no-runtime','given':{'role':'unknown','model_failure':'model_budget_unverified'},'expect':{}}
    observed=await run_scenario(db,case)
    report=observed['operation'].report
    assert observed['model_calls']==0
    assert report.source_outcome=='completed' and report.analysis_outcome=='failed'
    assert any(c.reason=='model_budget_unverified' for c in report.contacts)

@pytest.mark.asyncio
async def test_disappeared_room_is_partial_for_batch_and_does_not_block_other_customer(db):
    from copy import deepcopy
    from tests.organize_scenarios import run_scenario
    case=deepcopy(next(c for c in load_cases() if c['id']=='mixed_account_batch'))
    case['given'].pop('room_failure');case['given']['source_missing_rooms']=['room-a']
    result=await run_scenario(db,case)
    assert result['source_outcome']=='partial' and result['model_calls']==1
    assert all(i.scope=='conversation' for i in result['operation'].report.issues if i.code=='source_conversation_unavailable')
