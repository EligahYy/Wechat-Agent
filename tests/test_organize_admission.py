import pytest
from tests.test_single_customer_flow import flow,review,sync
from tests.fakes.source import FakeSource
from tests.factories import make_page
from wechat_agent.source.contracts import ConversationRecord
from wechat_agent.source.adapter import SourceError

@pytest.mark.asyncio
async def test_unknown_unrelated_group_allows_actual_first_model_and_report(flow):
    client,calls,_=flow;review(client)
    source=client.app.state.services.source
    source.rooms.append(ConversationRecord(account_id='acct-1',conversation_id='unrelated',kind='group',title='无关群',membership_state='unknown'))
    result=await sync(client)
    assert len(calls)==1 and result.report.analysis_outcome=='updated'
    assert result.report.source_outcome=='completed'
    assert any(i.severity=='warning' for i in result.report.issues)

@pytest.mark.asyncio
async def test_known_room_failure_never_calls_model_and_report_explains(flow):
    client,calls,_=flow;review(client)
    class Broken(FakeSource):
        async def messages(self,*args):raise SourceError('source_timeout')
    client.app.state.services.source=Broken()
    result=await sync(client)
    assert not calls
    assert result.state=='failed' and result.report.analysis_outcome=='not_started'
    assert any(i.code=='source_timeout' for c in result.report.contacts for i in c.issues)

@pytest.mark.asyncio
async def test_partially_rejected_field_is_visible_as_partial_not_complete(flow):
    client,calls,payload=flow;review(client)
    payload['goods']['volume']['value']='999999方'
    result=await sync(client)
    assert result.report.analysis_outcome=='partial'
    assert any(i.code=='profile_field_invalid' for c in result.report.contacts for i in c.issues)
    repeated=await sync(client,'repeat-partial')
    assert len(calls)==1 and repeated.report.analysis_outcome=='unchanged'
    assert any(i.code=='profile_field_invalid' for c in repeated.report.contacts for i in c.issues)

@pytest.mark.asyncio
async def test_account_scope_keeps_the_same_unknown_coverage_warning(flow):
    client,calls,_=flow;review(client)
    source=client.app.state.services.source
    source.rooms.append(ConversationRecord(account_id='acct-1',conversation_id='unknown',kind='group',title='未知群',membership_state='unknown'))
    source.pages['unknown']=[make_page([],conversation_id='unknown')]
    result=await sync(client,contact=None)
    assert any(i.code=='source_group_membership_unverified' for i in result.report.issues)

    from contextlib import closing
    from wechat_agent.storage.db import open_existing_db
    import json
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        manifest=json.loads(conn.execute("SELECT manifest_json FROM snapshots WHERE account_id='acct-1' AND contact_id='merchant-a' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
        assert 'source_group_membership_unverified' in manifest['coverage']['warning_codes']


@pytest.mark.asyncio
@pytest.mark.parametrize('additional_gap,empty', [(None,False),('source_shards_unavailable',False),(None,True)])
async def test_numberless_rows_allow_only_the_verified_archive_to_publish(flow, additional_gap, empty):
    import json
    from wechat_agent.source.contracts import SourceIssue

    client, calls, payload = flow
    payload['gaps'] = ['source_message_id_unavailable:invented-room']
    if empty:
        payload.clear()
        payload['contact_id'] = 'merchant-a'
    review(client)
    source = client.app.state.services.source
    page = source.pages['group-1'][0]
    code = 'source_message_id_unavailable'
    issue = SourceIssue(code=code, raw={'talker':'group-1', 'server_id':0, 'content':'quarantined row'})
    source.pages['group-1'] = [page.model_copy(update={
        'gaps': [code] + ([additional_gap] if additional_gap else []),
        'complete': False,
        'issues': [issue],
    })]
    result = await sync(client)
    profile = client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()
    assert result.report.source_outcome == 'partial'
    if additional_gap:
        assert not calls and profile['model_version'] == 0
        assert result.state == 'failed'
        return
    if empty:
        assert len(calls) == 1 and profile['model_version'] == 0
        assert result.state == 'succeeded'
        assert result.report.analysis_outcome == 'no_findings'
        assert any(i.code == code and i.severity == 'warning' for i in result.report.contacts[0].issues)
        return
    assert len(calls) == 1 and profile['model_version'] == 1
    assert result.state == 'succeeded'
    assert result.report.analysis_outcome == 'partial'
    assert 'quarantined row' not in json.dumps(calls)
    assert 'source_message_id_unavailable:group-1' in profile['issues']
    assert 'source_message_id_unavailable:invented-room' not in profile['issues']
    assert any(i.code == code and i.conversation_id == 'group-1'
               and i.severity == 'warning' for i in result.report.contacts[0].issues)
