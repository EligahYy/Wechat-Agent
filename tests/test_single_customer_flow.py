import json
from contextlib import closing
from pathlib import Path
import httpx
import pytest
from tests.factories import seed_case,make_message,make_page
from tests.fakes.source import FakeSource
from wechat_agent.storage.db import open_existing_db
from wechat_agent.operations.worker import run_next

@pytest.fixture
def flow(client):
    with closing(open_existing_db(client.app.state.database_path)) as db:seed_case(db)
    client.app.state.services.source=FakeSource()
    class Credentials:
        def __init__(self):self.values={}
        def get(self,key):return self.values[key]
        def set(self,key,value):self.values[key]=value
    client.app.state.services.credential_store=Credentials()
    calls=[]
    payload=json.loads((Path(__file__).parent/'fixtures/profile-ready.json').read_text())
    def transport(request):
        body=json.loads(request.content)
        if body['messages'][-1]['content']=='Return {"probe":"ok"}.':content='{"probe":"ok"}'
        else:calls.append(body);content=json.dumps(payload)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':content}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    response=client.put('/api/model',json={'account_id':'acct-1','expected_version':0,'endpoint':'https://synthetic.example/chat/completions','model_id':'synthetic','response_mode':'json_object','context_tokens':128000,'max_output_tokens':8192,'api_key':'synthetic-key'})
    assert response.status_code==200
    assert client.post('/api/model/check',json={'account_id':'acct-1','expected_version':1}).status_code==200
    return client,calls,payload

def review(client):
    response=client.post('/api/model/budget-review',json={'account_id':'acct-1','expected_version':1,'reference':'https://docs.example/model-budget','acknowledged':True})
    assert response.status_code==200,response.text
    assert response.json()['runtime_ready'] is True
    assert response.json()['connection']['capacity_verified'] is False

async def sync(client,key='first',contact='merchant-a'):
    response=client.post('/api/operations',json={'action':'sync_and_organize','scope':{'account_id':'acct-1',**({'contact_id':contact} if contact else {})},'idempotency_key':key})
    assert response.status_code==202,response.text
    with closing(open_existing_db(client.app.state.database_path)) as db:return await run_next(db,client.app.state.services)

@pytest.mark.asyncio
async def test_only_requested_customer_is_analyzed_and_unchanged_sync_skips_paid_call(flow):
    client,calls,_=flow;review(client)
    first=await sync(client)
    assert first.source_state=='succeeded' and first.counts['analysis_completed']==1
    assert len(calls)==1 and json.loads(calls[0]['messages'][-1]['content'])['contact_id']=='merchant-a'
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version']==1
    assert client.get('/api/contacts/merchant-b/profile?account_id=acct-1').json()['model_version']==0
    reads=len(client.app.state.services.source.calls)
    second=await sync(client,'second')
    assert len(client.app.state.services.source.calls)>reads
    assert len(calls)==1 and second.counts['analysis_skipped']==1

@pytest.mark.asyncio
async def test_connection_pass_without_budget_review_never_sends_customer_material(flow):
    client,calls,_=flow
    operation=await sync(client)
    assert operation.source_state=='succeeded' and operation.error_code=='model_budget_unverified'
    assert operation.counts['analysis_failed']==1
    assert not calls

@pytest.mark.asyncio
async def test_source_failure_never_claims_unchanged_or_calls_model(flow):
    client,calls,_=flow;review(client)
    from wechat_agent.source.adapter import SourceError
    class Broken(FakeSource):
        async def messages(self,*args):raise SourceError('source_unreachable')
    client.app.state.services.source=Broken()
    operation=await sync(client)
    assert operation.source_state=='failed' and operation.state=='failed' and not calls

@pytest.mark.asyncio
async def test_manual_change_requires_reanalysis_and_human_value_survives(flow):
    client,calls,_=flow;review(client);await sync(client)
    assert client.patch('/api/contacts/merchant-a/manual',json={'account_id':'acct-1','expected_version':0,'fields':{'goods.volume':'人工15方'}}).status_code==200
    await sync(client,'after-manual')
    assert len(calls)==2
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['effective']['goods']['volume']['value']=='人工15方'

@pytest.mark.asyncio
async def test_late_model_result_after_stop_never_publishes(flow):
    client,calls,payload=flow;review(client)
    def transport(request):
        calls.append(request)
        operation=client.get('/api/operations?account_id=acct-1').json()['items'][0]
        client.post('/api/operations',json={'action':'stop','account_id':'acct-1','operation_id':operation['id']})
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    operation=await sync(client)
    assert operation.state=='stopped'
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version']==0

@pytest.mark.asyncio
async def test_changed_role_during_model_call_prevents_publication(flow):
    client,calls,payload=flow;review(client)
    def transport(request):
        with closing(open_existing_db(client.app.state.database_path)) as db,db:db.execute("UPDATE contacts SET role='provider',role_version=role_version+1 WHERE contact_id='merchant-a'")
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    operation=await sync(client)
    assert operation.error_code=='contact_changed'
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version']==0

def test_budget_review_binds_config_and_never_asserts_vision_or_measured_capacity(flow):
    client,calls,_=flow;review(client)
    original=client.get('/api/model?account_id=acct-1').json()
    assert original['budget_review']['method']=='operator_document_review' and not calls
    assert original['connection']['vision_verified'] is False
    result=client.put('/api/model',json={'account_id':'acct-1','expected_version':1,'endpoint':original['endpoint'],'model_id':'different','response_mode':'json_object','context_tokens':128000,'max_output_tokens':8192})
    assert result.status_code==200 and result.json()['runtime_ready'] is False

@pytest.mark.asyncio
async def test_append_during_model_publishes_frozen_result_as_pending(flow):
    from datetime import datetime,timezone
    from wechat_agent.source.repository import archive_page
    client,calls,payload=flow;review(client)
    def transport(request):
        calls.append(request)
        with closing(open_existing_db(client.app.state.database_path)) as db:
            archive_page(db,make_page([make_message(message_id='during-model',body='新增需求',sent_at=datetime.now(timezone.utc))]))
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    await sync(client)
    profile=client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()
    assert profile['model_version']==1 and profile['pending'] is True and len(calls)==1

@pytest.mark.asyncio
async def test_model_failure_preserves_previous_profile_and_source_success(flow):
    client,calls,payload=flow;review(client);await sync(client)
    client.patch('/api/contacts/merchant-a/manual',json={'account_id':'acct-1','expected_version':0,'notes':{'goods':'changed input'}})
    wrong={**payload,'contact_id':'merchant-b'}
    client.app.state.services.model_transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(wrong)}}]}))
    result=await sync(client,'bad-model')
    assert result.source_state=='succeeded' and result.error_code=='target_mismatch'
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version']==1

@pytest.mark.asyncio
async def test_runtime_config_is_frozen_when_settings_change_during_call(flow):
    client,calls,payload=flow;review(client)
    def transport(request):
        calls.append(request)
        response=client.put('/api/model',json={'account_id':'acct-1','expected_version':1,'endpoint':'https://synthetic.example/chat/completions','model_id':'new-model','response_mode':'json_object','context_tokens':128000,'max_output_tokens':8192})
        assert response.status_code==200
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    await sync(client)
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version']==1
    result=await sync(client,'after-config-change')
    assert result.error_code=='model_budget_unverified' and len(calls)==1

@pytest.mark.asyncio
async def test_sync_updates_other_merchant_pending_without_analyzing_them(flow):
    from datetime import datetime,timezone
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.source.contracts import ContactKey
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.contracts import OperationScope,CancellationToken
    client,calls,_=flow;review(client)
    with closing(open_existing_db(client.app.state.database_path)) as db:
        snapshot=build_snapshot(db,ContactKey(account_id='acct-1',contact_id='merchant-b'),datetime.now(timezone.utc))
        op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-b'),'seed-b')
        candidate={'contact_id':'merchant-b','communication':{'summary':{'state':'known','value':'已发出','sources':[{'message_id':'fixture:group-1:2','revision':1}]}}}
        assert publish(db,snapshot,candidate,CancellationToken(operation_id=op.id,generation=op.generation)).version==1
        with db:db.execute("UPDATE operations SET state='succeeded' WHERE id=?",(op.id,))
    source=client.app.state.services.source
    page=source.pages['group-1'][0]
    source.pages['group-1'][0]=page.model_copy(update={'records':[*page.records,make_message(message_id='other-new',sender_id='merchant-b',body='新一批需求')]})
    await sync(client)
    assert len(calls)==1
    assert client.get('/api/contacts/merchant-b/profile?account_id=acct-1').json()['pending'] is True

@pytest.mark.parametrize('updates',[{'acknowledged':False},{'acknowledged':1},{'reference':'https://user:secret@docs.example/private'},{'reference':'http://docs.example'}, {'expected_version':2}])
def test_budget_review_rejects_invalid_or_stale_record_without_model_call(flow,updates):
    client,calls,_=flow
    response=client.post('/api/model/budget-review',json={'account_id':'acct-1','expected_version':1,'reference':'https://docs.example/model-budget','acknowledged':True,**updates})
    assert response.status_code in (409,422) and not calls
    assert client.get('/api/model?account_id=acct-1').json()['runtime_ready'] is False

@pytest.mark.asyncio
async def test_model_session_setup_failure_does_not_relabel_source_as_failed(flow):
    client,calls,_=flow
    class BrokenSession:
        async def __aenter__(self):raise RuntimeError('synthetic runtime setup failure')
        async def __aexit__(self,*args):pass
    client.app.state.services.analysis_factory=lambda *args:BrokenSession()
    result=await sync(client)
    assert result.source_state=='succeeded' and result.phase=='analysis'
    assert result.error_code=='analysis_failed' and not calls
    assert result.report.analysis_outcome=='failed'
    assert result.report.source_outcome=='completed'
