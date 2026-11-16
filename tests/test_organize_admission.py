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
