import json
from datetime import datetime,timezone
import httpx
import pytest
from wechat_agent.model.contracts import ModelConfig,ModelCapabilities,ModelCallError
from wechat_agent.model.gateway import ModelGateway
from wechat_agent.context.builder import build_snapshot


@pytest.fixture
def workflow_env(db,snapshot,analysis_result,cancellation):
    caps=ModelCapabilities(model_id='synthetic',context_tokens=128000,max_output_tokens=8192,structured_output=True,vision=False,verified_at=datetime.now(timezone.utc))
    config=ModelConfig(version='config-1',endpoint='https://model.example/chat/completions',model_id='synthetic',credential_ref='test',capabilities=caps)
    snapshot=build_snapshot(db,snapshot.key,snapshot.cutoff,versions={**snapshot.versions,'model_config':'config-1'})
    calls=[]
    async def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':analysis_result.model_dump_json()}}]})
    class Credentials:
        def get(self,ref):return 'synthetic-secret'
    client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return ModelGateway(db,config,client,Credentials()),snapshot,cancellation,calls,client


@pytest.mark.asyncio
async def test_workflow_uses_full_frozen_context_without_publishing(db,workflow_env):
    from wechat_agent.analysis.workflow import WorkflowV1
    gateway,snapshot,token,calls,client=workflow_env
    async with client:result=await WorkflowV1(db,gateway).run(snapshot,None,token)
    assert result.contact_id=='merchant-a' and len(calls)==1
    payload=json.loads(calls[0]['messages'][-1]['content'])
    assert len(payload['messages'])==4 and payload['contact_id']=='merchant-a'
    assert len({row['sender_id'] for row in payload['messages']})>=3
    assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0
    assert db.execute('SELECT status FROM model_calls').fetchone()[0]=='succeeded'


@pytest.mark.asyncio
async def test_workflow_checks_manual_scope_before_any_paid_call(db,workflow_env):
    from wechat_agent.analysis.workflow import WorkflowV1
    from wechat_agent.contacts.scope import set_scope
    gateway,snapshot,token,calls,client=workflow_env
    set_scope(db,[snapshot.key],False,{'merchant-a':0})
    async with client:
        with pytest.raises(ModelCallError) as error:await WorkflowV1(db,gateway).run(snapshot,None,token)
    assert error.value.code=='scope_excluded' and not calls


@pytest.mark.asyncio
async def test_oversized_workflow_refuses_without_truncating(db,workflow_env):
    from wechat_agent.analysis.workflow import WorkflowV1
    gateway,snapshot,token,calls,client=workflow_env
    from wechat_agent.source.repository import archive_page
    from tests.factories import make_message,make_page
    archive_page(db,make_page([make_message(message_id='oversized',body='资料'*90000)]))
    snapshot=build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)
    async with client:
        with pytest.raises(ModelCallError) as error:await WorkflowV1(db,gateway).run(snapshot,None,token)
    assert error.value.code=='context_requires_chunking' and not calls


@pytest.mark.asyncio
async def test_workflow_uses_frozen_manual_constraints(db,workflow_env):
    from wechat_agent.profiles.manual import save_manual
    from wechat_agent.analysis.workflow import WorkflowV1
    gateway,snapshot,token,calls,client=workflow_env
    save_manual(db,snapshot.key,{'fields':{'goods.volume':'15方'},'notes':{'goods':'人工补充'}},0)
    current=build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)
    async with client:await WorkflowV1(db,gateway).run(current,None,token)
    payload=json.loads(calls[0]['messages'][-1]['content'])
    assert payload['manual_constraints']['fields']['goods.volume']=='15方'
    assert payload['manual_constraints']['notes']['goods']=='人工补充'
