import json
from datetime import datetime,timezone
import httpx
import pytest
from tests.factories import seed_case

@pytest.fixture
def setup_gateway(db,snapshot):
    from wechat_agent.model.contracts import ModelConfig,ModelRequest,ModelCapabilities
    from wechat_agent.model.gateway import ModelGateway
    from wechat_agent.operations.contracts import OperationScope,CancellationToken
    from wechat_agent.operations.service import create_operation
    operation=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'gateway-test')
    token=CancellationToken(operation_id=operation.id,generation=operation.generation)
    capability=ModelCapabilities(model_id='synthetic',context_tokens=16000,max_output_tokens=1000,structured_output=True,vision=False,verified_at=datetime.now(timezone.utc))
    config=ModelConfig(version='config-1',endpoint='https://model.example/chat/completions',model_id='synthetic',credential_ref='test',capabilities=capability)
    from wechat_agent.context.builder import build_snapshot
    snapshot=build_snapshot(db,snapshot.key,snapshot.cutoff,versions={**snapshot.versions,'model_config':'config-1'})
    request=ModelRequest(call_id='call',unit_id='unit',snapshot_id=snapshot.id,phase='extract',model_config_version='config-1',messages=[{'role':'user','content':'synthetic input'}],output_schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},output_tokens=100)
    calls=[];responses=[];delays=[]
    async def transport(req):
        calls.append(req)
        value=responses.pop(0)
        if isinstance(value,Exception):raise value
        return value
    class Credentials:
        def get(self,ref):return 'secret-not-for-logs'
    async def sleep(delay):delays.append(delay)
    client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    gateway=ModelGateway(db,config,client,Credentials(),sleep=sleep)
    return gateway,request,token,responses,calls,delays,client

def answer(content='{"ok":true}',reason='stop'):
    return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':reason,'message':{'content':content}}],'usage':{'prompt_tokens':4,'completion_tokens':3}})

@pytest.mark.asyncio
async def test_retry_after_and_audit_preserve_call_identity(setup_gateway,db):
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.Response(429,headers={'Retry-After':'2'}),answer()])
    async with client:result=await gateway.generate(request,token)
    assert result.payload=={'ok':True} and len(calls)==2 and delays==[2]
    assert all(call.headers['X-Request-ID']=='call' for call in calls)
    rows=db.execute('SELECT status,call_id FROM model_calls ORDER BY attempt').fetchall()
    assert [row['status'] for row in rows]==['rate_limited','succeeded']
    assert all(row['call_id']=='call' for row in rows)

@pytest.mark.asyncio
@pytest.mark.parametrize('status,code',[(401,'authentication_failed'),(400,'request_invalid'),(404,'model_not_found')])
async def test_non_retryable_errors_do_not_loop(setup_gateway,status,code):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.append(httpx.Response(status,json={'error':'secret-not-for-logs'}))
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code==code and len(calls)==1
    assert 'secret-not-for-logs' not in str(error.value)

@pytest.mark.asyncio
async def test_format_repair_once_then_fail(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([answer('invalid'),answer('{"wrong":1}')])
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='output_invalid' and len(calls)==2
    assert json.loads(calls[1].content)['messages'][0]==json.loads(calls[0].content)['messages'][0]

@pytest.mark.asyncio
async def test_truncation_and_cancel_never_succeed(setup_gateway,db):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.append(answer(reason='length'))
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='output_truncated'
    assert db.execute("SELECT COUNT(*) FROM model_calls WHERE status='succeeded'").fetchone()[0]==0

@pytest.mark.asyncio
async def test_shared_unit_budget_cannot_be_reset_by_call_id(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.Response(503) for _ in range(6)])
    async with client:
        for identifier in ['one','two','three']:
            with pytest.raises(ModelCallError):await gateway.generate(request.model_copy(update={'call_id':identifier}),token)
    assert len(calls)==6

@pytest.mark.asyncio
async def test_stopped_operation_does_not_send(setup_gateway,db):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    db.execute("UPDATE operations SET state='stopped'");db.commit()
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='model_cancelled' and calls==[]

@pytest.mark.asyncio
async def test_cancel_after_response_never_records_success(setup_gateway,db):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    async def transport(req):
        db.execute('UPDATE operations SET generation=generation+1');db.commit()
        return answer()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as replacement:
        gateway.client=replacement
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    await client.aclose()
    assert error.value.code=='model_cancelled'
    assert db.execute("SELECT COUNT(*) FROM model_calls WHERE status='succeeded'").fetchone()[0]==0

@pytest.mark.asyncio
async def test_invalid_schema_never_contacts_model(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request.model_copy(update={'output_schema':{'type':'not-a-type'}}),token)
    assert error.value.code=='output_schema_invalid' and calls==[]

@pytest.mark.asyncio
async def test_malformed_usage_is_sanitized(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    malformed=answer().json();malformed['usage']='bad'
    responses.extend([httpx.Response(200,json=malformed),httpx.Response(200,json=malformed)])
    async with client:result=await gateway.generate(request,token)
    assert result.payload=={'ok':True} and result.usage=={} and len(calls)==1

@pytest.mark.asyncio
async def test_repair_does_not_reset_call_budget(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.Response(503),httpx.Response(503),answer('invalid'),httpx.Response(503),httpx.Response(503),answer()])
    async with client:
        with pytest.raises(ModelCallError):await gateway.generate(request,token)
    assert len(calls)==3

@pytest.mark.asyncio
async def test_repeating_call_id_cannot_reset_call_budget(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.Response(503) for _ in range(6)])
    async with client:
        for _ in range(2):
            with pytest.raises(ModelCallError):await gateway.generate(request,token)
    assert len(calls)==3

@pytest.mark.asyncio
async def test_json_object_default_contains_schema_instructions(setup_gateway):
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.append(answer())
    async with client:await gateway.generate(request,token)
    payload=json.loads(calls[0].content)
    assert payload['response_format']=={'type':'json_object'}
    assert any(json.dumps(request.output_schema,sort_keys=True) in item['content'] for item in payload['messages'])

@pytest.mark.asyncio
@pytest.mark.parametrize('schema',[{'$ref':'#/$defs/missing'},{'$dynamicRef':'https://untrusted.invalid/schema'}])
async def test_unresolved_or_external_schema_rejected_before_sending(setup_gateway,schema):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.Response(503) for _ in range(3)])
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request.model_copy(update={'output_schema':schema}),token)
    assert error.value.code=='output_schema_invalid' and calls==[]

@pytest.mark.asyncio
async def test_transport_timeouts_keep_their_classification(setup_gateway):
    from wechat_agent.model.contracts import ModelCallError
    gateway,request,token,responses,calls,delays,client=setup_gateway
    responses.extend([httpx.ReadTimeout('synthetic') for _ in range(3)])
    async with client:
        with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
    assert error.value.code=='model_timeout' and len(calls)==2


@pytest.mark.asyncio
async def test_retry_after_beyond_remaining_deadline_does_not_timeout(setup_gateway, monkeypatch):
    from wechat_agent.model import gateway as gateway_module
    from wechat_agent.model.contracts import ModelCallError

    gateway, request, token, responses, calls, delays, client = setup_gateway
    clock = iter([0, 0, 1, 25, 25])
    monkeypatch.setattr(gateway_module, 'monotonic', lambda: next(clock))
    responses.append(httpx.Response(429, headers={'Retry-After': '100'}))
    async with client:
        with pytest.raises(ModelCallError) as error:
            await gateway.generate(request, token)
    assert error.value.code == 'retry_after_exceeds_deadline'
    assert len(calls) == 1 and delays == []


@pytest.mark.asyncio
async def test_unit_deadline_records_timeout_and_format_repair(setup_gateway, db):
    from asyncio import sleep, get_running_loop
    from contextlib import asynccontextmanager
    from wechat_agent.model.contracts import ModelCallError

    gateway, request, token, _, _, _, client = setup_gateway
    calls = []

    @asynccontextmanager
    async def stream(*args, **kwargs):
        calls.append(kwargs['json'])
        if len(calls) == 1:
            yield answer('invalid json')
        else:
            await sleep(1)

    gateway.client.stream = stream
    async with client:
        with pytest.raises(ModelCallError) as error:
            await gateway.generate(request, token, deadline=get_running_loop().time() + .08)
    assert error.value.code == 'model_timeout'
    audit = db.execute('SELECT status FROM model_calls ORDER BY attempt').fetchall()
    assert [row[0] for row in audit] == ['output_invalid', 'model_timeout']
    counts = json.loads(db.execute('SELECT counts_json FROM operations WHERE id=?', (token.operation_id,)).fetchone()[0])
    assert counts['model_attempt_format_repair'] == 1
    assert counts['model_failure_output_invalid'] == counts['model_failure_model_timeout'] == 1


@pytest.mark.asyncio
async def test_connect_timeout_is_distinguished_from_provider_response_timeout(setup_gateway, db):
    from wechat_agent.model.contracts import ModelCallError

    gateway, request, token, responses, calls, _, client = setup_gateway
    responses.append(httpx.ConnectTimeout('connect stalled'))
    async with client:
        with pytest.raises(ModelCallError) as error:
            await gateway.generate(request.model_copy(update={'high_value_history': True}), token)
    assert error.value.code == 'model_connect_timeout'
    assert len(calls) == 1
    assert db.execute('SELECT status FROM model_calls').fetchone()[0] == 'model_connect_timeout'


@pytest.mark.parametrize('old_state', ['succeeded', 'failed'])
def test_deepseek_request_policy_reuses_only_verified_previous_checkpoints(setup_gateway, db, old_state):
    from wechat_agent.analysis.checkpoints import checkpoint, create_run, register_unit, unit_cache_key
    from wechat_agent.context.contracts import ContextSnapshot
    from wechat_agent.model.contracts import ModelMessage

    gateway, request, token, *_ = setup_gateway
    snapshot = ContextSnapshot.model_validate_json(db.execute(
        'SELECT manifest_json FROM snapshots WHERE snapshot_id=?', (request.snapshot_id,)
    ).fetchone()[0])
    config = gateway.config.model_copy(update={
        'endpoint': 'https://api.deepseek.com/v1/chat/completions',
        'model_id': 'deepseek-v4-flash',
        'capabilities': gateway.config.capabilities.model_copy(update={'model_id': 'deepseek-v4-flash'}),
    })
    request = request.model_copy(update={'messages': [ModelMessage(role='user', content='{"messages":[]}')]})
    create_run(db, snapshot, token, 'direct', config)
    legacy_key = unit_cache_key(snapshot, request, ())
    output = '{"contact_id":"merchant-a"}' if old_state == 'succeeded' else None
    with db:
        db.execute('''INSERT INTO history_checkpoints VALUES(?,?,?,?,?,?,?,?)''',
                   ('acct-1', 'merchant-a', legacy_key, 'extract', old_state, 6, output,
                    None if output else 'output_truncated'))
    new_request = register_unit(db, snapshot, token, request, (), 0, config)
    saved = checkpoint(db, snapshot, new_request)
    assert new_request.checkpoint_key != legacy_key
    assert saved['requests'] == 0 and saved['error_code'] is None
    assert saved['state'] == ('succeeded' if output else 'pending')
    assert saved['output_json'] == output


@pytest.mark.parametrize('endpoint,model_id,phase,purpose,enabled', [
    ('https://api.deepseek.com:443/v1/chat/completions','deepseek-v4-pro','merge','profile',True),
    ('https://api.deepseek.com/chat/completions','deepseek-flash','verify','discovery',False),
    ('https://api.deepseek.com/chat/completions','deepseek-reasoner','extract','profile',False),
    ('https://proxy.example/chat/completions','deepseek-flash','extract','profile',False),
])
def test_provider_payload_keeps_other_endpoints_and_purposes_compatible(setup_gateway, endpoint, model_id, phase, purpose, enabled):
    from wechat_agent.context.tokens import wire_payload
    gateway, request, *_ = setup_gateway
    config = gateway.config.model_copy(update={'endpoint': endpoint, 'model_id': model_id})
    request = request.model_copy(update={'phase': phase, 'purpose': purpose})
    payload = wire_payload(request, config)
    assert payload.get('thinking') == ({'type': 'disabled'} if enabled else None)


@pytest.mark.asyncio
@pytest.mark.parametrize('finish_reason', ['length', 'stop'])
async def test_other_endpoints_keep_existing_empty_result_recovery(setup_gateway, finish_reason):
    from wechat_agent.model.contracts import ModelCallError

    gateway, request, token, responses, calls, _, client = setup_gateway
    request = request.model_copy(update={'high_value_history':True})
    responses.append(httpx.Response(200, json={'model':'synthetic','choices':[
        {'finish_reason':finish_reason,'message':{'content':'','reasoning_content':'synthetic'}}
    ]}))
    responses.append(answer())
    async with client:
        if finish_reason == 'stop':
            assert (await gateway.generate(request, token)).payload == {'ok': True}
            assert [json.loads(call.content)['max_tokens'] for call in calls] == [100, 100]
        else:
            with pytest.raises(ModelCallError, match='模型请求未完成') as error:
                await gateway.generate(request, token)
            assert error.value.code == 'output_truncated'
            assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('headers_received', [False, True])
async def test_deadline_distinguishes_waiting_for_headers_and_reading_body(setup_gateway, db, headers_received):
    import asyncio
    from wechat_agent.model.contracts import ModelCallError

    gateway, request, token, *_ = setup_gateway

    class StalledBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.sleep(1)

    async def respond(_):
        if not headers_received:
            await asyncio.sleep(1)
        return httpx.Response(200, stream=StalledBody())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway.client = client
        with pytest.raises(ModelCallError) as error:
            await gateway.generate(request, token, deadline=asyncio.get_running_loop().time() + .1)
    case = 'reading_body' if headers_received else 'before_headers'
    assert error.value.code == 'model_timeout'
    call = db.execute('SELECT usage_json FROM model_calls').fetchone()
    usage = json.loads(call[0])
    assert usage['timeout_stage'] == case
    assert ('response_headers_ms' in usage) == headers_received
    counts = json.loads(db.execute('SELECT counts_json FROM operations WHERE id=?',(token.operation_id,)).fetchone()[0])
    assert counts[f'model_timeout_{case}'] == 1
