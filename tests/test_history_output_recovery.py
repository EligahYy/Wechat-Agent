import json
import httpx
import pytest
from tests.test_history_workflow import history_env
from tests.test_model_gateway import setup_gateway
from wechat_agent.analysis.history import WorkflowV2
from wechat_agent.model.contracts import ModelCallError


def test_profile_request_uses_configured_output_above_8192(history_env):
    e=history_env
    e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':200000,'max_output_tokens':32000})})
    request=WorkflowV2(e.gateway.conn,e.gateway).request(e.snapshot,{'messages':[]},'rules')
    assert request.output_tokens==32000

@pytest.mark.asyncio
async def test_truncated_response_retains_safe_usage_and_requested_output(setup_gateway,db):
    gateway,request,token,responses,calls,_,client=setup_gateway
    responses.append(httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length','message':{'content':'incomplete','reasoning_content':'PRIVATE REASONING'}}],
        'usage':{'prompt_tokens':100,'completion_tokens':100,'completion_tokens_details':{'reasoning_tokens':95},'private':'SECRET'}}))
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='output_truncated'
    audit=json.loads(db.execute('SELECT usage_json FROM model_calls').fetchone()[0])
    assert audit['requested_output_tokens']==100 and audit['completion_tokens']==100 and audit['reasoning_tokens']==95
    assert 'SECRET' not in json.dumps(audit) and 'PRIVATE' not in json.dumps(audit)

@pytest.mark.asyncio
async def test_output_length_with_large_input_window_splits_then_assembles(db,history_env):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.analysis.coverage import compute_coverage
    e=history_env;original=e.client._transport.handler;calls=[]
    e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':500000})})
    async def response(request):
        payload=json.loads(json.loads(request.content)['messages'][-1]['content']);calls.append(payload)
        unit=payload.get('history_unit',{})
        if not unit or (unit.get('phase')=='extract' and len(unit.get('primary_spans',[]))>3) or (unit.get('phase')=='merge' and unit['field']=='all'):
            return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length','message':{'content':'{"partial":'}}]})
        return await original(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        e.gateway.client=client
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert compute_coverage(db,'acct-1',e.snapshot.id).complete
        assert len(calls)>3
        assert db.execute('SELECT COUNT(*) FROM history_run_units WHERE superseded=1').fetchone()[0]>0
        e.retry('resumed-output');calls.clear()
        recovered=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert calls==[]
        assert publish(db,e.snapshot,recovered,e.token).version==1

@pytest.mark.asyncio
async def test_permanent_truncation_is_bounded_and_does_not_publish_or_repay(db,history_env):
    e=history_env;calls=[]
    async def response(request):
        calls.append(request)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length','message':{'content':'{"incomplete"'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        e.gateway.client=client
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert 0<len(calls)<100
        assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0
        e.retry('still-truncated');calls.clear()
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert calls==[]

def test_subdividing_existing_fragment_keeps_original_unicode_offsets():
    from tests.test_context_chunks import request,config,message
    from wechat_agent.context.chunks import plan_chunks
    whole=message(1,body='中文🙂'*5000)
    fragment={**whole,'body':whole['body'][1000:8000],'body_fragment':{'start':1000,'end':8000,'total':15000}}
    chunks=plan_chunks([fragment],request,config(),input_limit=2000,context_messages=[whole])
    assert chunks[0].spans[0].start==1000 and chunks[-1].spans[-1].end==8000
    assert all(s.total==15000 for c in chunks for s in c.spans)
    assert ''.join(c.messages[-1]['body'] for c in chunks)==whole['body'][1000:8000]

@pytest.mark.asyncio
async def test_unproved_superseded_unit_cannot_hide_a_processing_gap(db,history_env):
    from wechat_agent.analysis.coverage import compute_coverage
    e=history_env
    async with e.client:await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    with db:db.execute('UPDATE history_run_units SET superseded=1 WHERE snapshot_id=?',(e.snapshot.id,))
    assert not compute_coverage(db,'acct-1',e.snapshot.id).complete

def test_declared_output_equal_to_window_still_leaves_room_for_work(history_env):
    from wechat_agent.context.tokens import request_budget
    e=history_env
    e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':32768,'max_output_tokens':32768})})
    request=WorkflowV2(db:=e.gateway.conn,e.gateway).request(e.snapshot,{'messages':[]},'rules')
    assert 0<request.output_tokens<32768
    assert request_budget(request,e.gateway.config).fits

@pytest.mark.asyncio
@pytest.mark.parametrize('usage',[None,'bad',{'completion_tokens_details':None}])
async def test_missing_or_malformed_usage_never_turns_length_into_format_repair(setup_gateway,usage):
    gateway,request,token,responses,calls,_,client=setup_gateway
    responses.append(httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length','message':{'content':'partial'}}],'usage':usage}))
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='output_truncated' and len(calls)==1
