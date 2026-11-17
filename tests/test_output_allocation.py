import httpx,json,pytest
from tests.test_model_gateway import setup_gateway,answer
from tests.test_history_workflow import history_env
from wechat_agent.analysis.history import WorkflowV2
from wechat_agent.model.contracts import ModelCallError

def test_large_declared_cap_is_not_sent_as_single_request(history_env):
 e=history_env;e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':1048000,'max_output_tokens':1000000})})
 req=WorkflowV2(e.gateway.conn,e.gateway).request(e.snapshot,{'messages':[]},'rules')
 assert req.output_tokens==8192

@pytest.mark.asyncio
async def test_length_grows_within_declared_cap_and_same_unit_budget(setup_gateway):
 gateway,request,token,responses,calls,_,client=setup_gateway
 request=request.model_copy(update={'allow_output_growth':True})
 responses.extend([answer(reason='length'),answer()])
 async with client:result=await gateway.generate(request,token)
 assert result.payload=={'ok':True}
 assert [json.loads(c.content)['max_tokens'] for c in calls]==[100,200]
 assert len({c.headers['X-Request-ID'] for c in calls})==1

@pytest.mark.asyncio
async def test_rejected_output_param_is_classified_without_leaking_provider_text(setup_gateway):
 gateway,request,token,responses,calls,_,client=setup_gateway
 responses.append(httpx.Response(400,json={'error':{'param':'max_tokens','message':'SECRET','code':'invalid_request_error'}}))
 async with client:
  with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
 assert error.value.code=='model_output_limit_rejected' and 'SECRET' not in str(error.value)

@pytest.mark.asyncio
@pytest.mark.parametrize('cap,expected',[(100,[100]),(150,[100,150]),(1000,[100,200,400])])
async def test_growth_never_exceeds_config_or_three_attempts(setup_gateway,cap,expected):
 gateway,request,token,responses,calls,_,client=setup_gateway
 gateway.config=gateway.config.model_copy(update={'capabilities':gateway.config.capabilities.model_copy(update={'max_output_tokens':cap})})
 request=request.model_copy(update={'allow_output_growth':True})
 responses.extend([answer(reason='length') for _ in expected])
 async with client:
  with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
 assert error.value.code=='output_truncated'
 assert [json.loads(c.content)['max_tokens'] for c in calls]==expected

@pytest.mark.asyncio
async def test_growth_must_fit_actual_remaining_context(setup_gateway):
 gateway,request,token,responses,calls,_,client=setup_gateway
 from wechat_agent.context.tokens import request_budget
 request=request.model_copy(update={'allow_output_growth':True,'output_tokens':1000})
 initial=request_budget(request,gateway.config)
 gateway.config=gateway.config.model_copy(update={'capabilities':gateway.config.capabilities.model_copy(update={'context_tokens':initial.input_tokens+1200,'max_output_tokens':1000})})
 responses.append(answer(reason='length'))
 async with client:
  with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
 assert len(calls)<=1 and error.value.code in {'output_truncated','context_requires_chunking'}

@pytest.mark.asyncio
async def test_bad_citation_gets_one_scoped_repair_then_validates(db,history_env):
 from wechat_agent.profiles.publisher import publish
 e=history_env;original=e.client._transport.handler;seen=[]
 e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':500000})})
 async def response(request):
  payload=json.loads(json.loads(request.content)['messages'][-1]['content']);seen.append(payload)
  if len(seen)==1:
   return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'contact_id':'merchant-a','goods':{'volume':{'value':'12方','state':'known','sources':[{'message_id':'invented-source','revision':1}]}}})}}]})
  assert payload['_source_correction']['allowed_sources']
  return await original(request)
 async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
  e.gateway.client=client
  result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
 assert len(seen)==2
 assert publish(db,e.snapshot,result,e.token).version==1
 counts=json.loads(db.execute('SELECT counts_json FROM operations WHERE id=?',(e.token.operation_id,)).fetchone()[0])
 assert counts['model_source_unknown']>0

@pytest.mark.asyncio
async def test_citation_repair_does_not_accept_unknown_refs_or_loop(db,history_env):
 e=history_env;seen=[]
 e.gateway.config=e.config.model_copy(update={'capabilities':e.config.capabilities.model_copy(update={'context_tokens':500000})})
 async def response(request):
  seen.append(request)
  return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'contact_id':'merchant-a','goods':{'volume':{'value':'12方','state':'known','sources':[{'message_id':'unknown','revision':1}]}}})}}]})
 async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
  e.gateway.client=client
  with pytest.raises(ModelCallError) as error:await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
 assert error.value.code=='chunk_source_outside_unit' and len(seen)==2
 assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['revision_mismatch','other_unit'])
async def test_citation_diagnostics_distinguish_revision_and_other_units(db,history_env,kind):
 e=history_env;original=e.client._transport.handler;calls=[]
 async def response(request):
  payload=json.loads(json.loads(request.content)['messages'][-1]['content']);calls.append(payload)
  if len(calls)==1:
   visible={r['message_id'] for r in payload['messages']}
   row=payload['messages'][0]
   ref={'message_id':row['message_id'],'revision':row['revision']+1} if kind=='revision_mismatch' else next(r.model_dump() for r in e.snapshot.material_refs if r.message_id not in visible)
   return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'contact_id':'merchant-a','goods':{'volume':{'value':'12方','state':'known','sources':[ref]}}})}}]})
  return await original(request)
 async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
  e.gateway.client=client
  await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
 counts=json.loads(db.execute('SELECT counts_json FROM operations WHERE id=?',(e.token.operation_id,)).fetchone()[0])
 assert counts['model_source_'+kind]==1 and counts['model_source_unknown']==0

@pytest.mark.asyncio
async def test_provider_rejects_growth_after_length_falls_back_to_splitting(setup_gateway):
 gateway,request,token,responses,calls,_,client=setup_gateway
 request=request.model_copy(update={'allow_output_growth':True})
 responses.extend([answer(reason='length'),httpx.Response(400,json={'error':{'param':'max_tokens','message':'above maximum'}})])
 async with client:
  with pytest.raises(ModelCallError) as error:await gateway.generate(request,token)
 assert error.value.code=='output_truncated'
 assert len(calls)==2
 assert gateway.output_ceiling==100
