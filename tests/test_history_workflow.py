"""Small real gateway window + large synthetic history, SQLite and real publisher."""
import json
from datetime import datetime,timezone
from types import SimpleNamespace
import httpx
import pytest
from tests.factories import make_message,make_page
from wechat_agent.context.builder import build_snapshot
from wechat_agent.model.contracts import ModelCapabilities,ModelConfig,ModelCallError
from wechat_agent.model.gateway import ModelGateway
from wechat_agent.operations.contracts import CancellationToken,OperationScope
from wechat_agent.operations.service import create_operation
from wechat_agent.source.repository import archive_page
from wechat_agent.profiles.contracts import AnalysisResult
from wechat_agent.profiles.publisher import publish

@pytest.fixture
def history_env(db,snapshot,cancellation):
    rows=[make_message(message_id=f'long-{i:03}',body=('收纳盒 12方 '+('历史语境资料 ' * 120)),sent_at=datetime(2026,11,11,10,i,tzinfo=timezone.utc)) for i in range(12)]
    archive_page(db,make_page(rows))
    cfg=ModelConfig(version='history-config',endpoint='https://model.test/chat/completions',model_id='synthetic',credential_ref='test',capabilities=ModelCapabilities(model_id='synthetic',context_tokens=24000,max_output_tokens=1024,structured_output=True,vision=False,verified_at=datetime.now(timezone.utc)))
    env=SimpleNamespace(config=cfg,calls=[],fail=None,invalid=False,cancel=False)
    async def transport(req):
        data=json.loads(req.content);payload=json.loads(data['messages'][-1]['content']);env.calls.append((data,payload))
        primary=payload.get('history_unit',{}).get('primary_spans',[])
        if env.cancel:
            with db:db.execute("UPDATE operations SET state='stop_requested' WHERE id=?",(env.token.operation_id,))
        if env.fail and any(s['message_id']==env.fail for s in primary):return httpx.Response(503)
        candidates=payload.get('candidates',[])
        sources=[{'message_id':s['message_id'],'revision':s['revision']} for s in primary]
        if not sources and 'messages' in payload:sources=[{'message_id':m['message_id'],'revision':m['revision']} for m in payload['messages']]
        if candidates:
            candidate=next((c for c in candidates if c.get('goods',{}).get('volume',{}).get('value')),{'contact_id':'merchant-a'})
        else:
            ref=next((s for s in sources if s['message_id'].startswith('long-')),sources[0] if sources else None)
            candidate={'contact_id':'merchant-a','goods':{'volume':{'state':'known','value':'12方','sources':[ref]}}} if ref else {'contact_id':'merchant-a'}
        if env.invalid:candidate={'contact_id':'merchant-a','goods':{'volume':{'state':'known','value':'12方','sources':[{'message_id':'foreign','revision':1}]}}}
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(candidate)}}]})
    class Credentials:
        def get(self,ref):return 'synthetic'
    async def no_sleep(delay):pass
    env.client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    env.gateway=ModelGateway(db,cfg,env.client,Credentials(),sleep=no_sleep)
    def freeze():return build_snapshot(db,snapshot.key,snapshot.cutoff,versions={**snapshot.versions,'strategy':'workflow-v2','model_config':'history-config'})
    env.freeze=freeze;env.snapshot=freeze();env.token=cancellation
    def retry(key='retry'):
        with db:db.execute("UPDATE operations SET state='failed' WHERE id=?",(env.token.operation_id,))
        op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),key)
        env.token=CancellationToken(operation_id=op.id,generation=op.generation);env.snapshot=freeze()
    env.retry=retry
    return env

@pytest.mark.asyncio
async def test_large_history_fits_each_call_and_publishes_with_complete_program_coverage(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.analysis.coverage import compute_coverage
    from wechat_agent.context.tokens import estimate_tokens
    e=history_env
    async with e.client:result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    assert len(e.calls)>2
    assert all(estimate_tokens(json.dumps(wire,ensure_ascii=False,separators=(',',':')),'synthetic')+wire['max_tokens']+2400+256<=24000 for wire,_ in e.calls)
    coverage=compute_coverage(db,e.snapshot.key.account_id,e.snapshot.id)
    assert coverage.complete and not coverage.pending and not coverage.failed
    assert len(coverage.processed)==len(e.snapshot.material_refs)
    assert publish(db,e.snapshot,result,e.token).version==1
    assert db.execute('SELECT COUNT(*) FROM history_checkpoints').fetchone()[0]>1

@pytest.mark.asyncio
async def test_failed_middle_retains_other_chunks_and_retry_only_sends_unfinished(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.analysis.coverage import compute_coverage
    e=history_env;e.fail='long-005'
    async with e.client:
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        coverage=compute_coverage(db,'acct-1',e.snapshot.id)
        assert coverage.failed and coverage.processed and not coverage.complete
        completed={r[0] for r in db.execute("SELECT cache_key FROM history_checkpoints WHERE state='succeeded'")}
        assert completed and db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0
        e.fail=None;e.retry();e.calls.clear()
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert compute_coverage(db,'acct-1',e.snapshot.id).complete
        counts=json.loads(db.execute('SELECT counts_json FROM operations WHERE id=?',(e.token.operation_id,)).fetchone()[0])
        assert counts['analysis_chunks_reused']>0
        assert counts['analysis_chunks_completed']==counts['analysis_chunks_total']
        sent_units={row[0] for row in db.execute('SELECT DISTINCT c.cache_key FROM model_calls m JOIN history_run_units u ON u.account_id=m.account_id AND u.snapshot_id=m.snapshot_id AND u.unit_id=m.unit_id JOIN history_checkpoints c ON c.account_id=u.account_id AND c.contact_id=u.contact_id AND c.cache_key=u.cache_key WHERE m.snapshot_id=?',(e.snapshot.id,))}
        assert not sent_units&completed
        assert publish(db,e.snapshot,result,e.token).version==1

@pytest.mark.asyncio
async def test_foreign_refs_are_not_cached_as_success_and_cancel_stops_further_calls(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env;e.invalid=True
    async with e.client:
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert db.execute("SELECT COUNT(*) FROM history_checkpoints WHERE state='succeeded'").fetchone()[0]==0
        e.invalid=False;e.retry();e.cancel=True;e.calls.clear()
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert len(e.calls)==1
        assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0

@pytest.mark.asyncio
async def test_retry_does_not_reset_six_network_request_budget(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env;e.fail='long-005'
    async with e.client:
        for key in ['first','second','third']:
            with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
            if key!='third':e.retry(key)
        assert max(r[0] for r in db.execute('SELECT requests FROM history_checkpoints'))==6
        failed_calls=[wire for wire,p in e.calls if any(s['message_id']=='long-005' for s in p.get('history_unit',{}).get('primary_spans',[]))]
        assert len(failed_calls)==6

@pytest.mark.asyncio
async def test_revision_reuses_unaffected_units_and_manual_change_invalidates_all(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.profiles.manual import save_manual
    e=history_env
    async with e.client:
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        e.retry('revision');e.calls.clear()
        archive_page(db,make_page([make_message(message_id='long-005',body='收纳盒 12方 修订资料 '+('历史语境资料 '*120),source_revision='revision-2')]))
        e.snapshot=e.freeze()
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert db.execute("SELECT COUNT(*) FROM history_run_units WHERE snapshot_id=? AND reused=1",(e.snapshot.id,)).fetchone()[0]>0
        assert any(s['message_id']=='long-005' and s['revision']==2 for _,p in e.calls for s in p.get('history_unit',{}).get('primary_spans',[]))
        e.retry('manual');save_manual(db,e.snapshot.key,{'fields':{'goods.volume':'人工15方'}},0);e.snapshot=e.freeze()
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert db.execute("SELECT COUNT(*) FROM history_run_units WHERE snapshot_id=? AND reused=1",(e.snapshot.id,)).fetchone()[0]==0

@pytest.mark.asyncio
async def test_restart_with_new_connection_reuses_persisted_results_and_respects_scope(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.storage.db import open_existing_db
    from wechat_agent.contacts.scope import set_scope
    e=history_env
    async with e.client:
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        e.retry('restart');e.calls.clear()
        path=db.execute('PRAGMA database_list').fetchone()[2]
        with open_existing_db(path) as reopened:
            e.gateway.conn=reopened
            await WorkflowV2(reopened,e.gateway).run(e.snapshot,None,e.token)
            assert not e.calls
            set_scope(reopened,[e.snapshot.key],False,{'merchant-a':0})
            with pytest.raises(ModelCallError) as error:await WorkflowV2(reopened,e.gateway).run(e.snapshot,None,e.token)
            assert error.value.code=='scope_excluded' and not e.calls
        e.gateway.conn=db

def test_program_coverage_rejects_missing_or_duplicated_spans(db,history_env):
    from wechat_agent.analysis.coverage import compute_coverage
    from wechat_agent.analysis.checkpoints import create_run
    e=history_env;create_run(db,e.snapshot,e.token,'chunked',e.config)
    coverage=compute_coverage(db,'acct-1',e.snapshot.id)
    assert not coverage.complete and len(coverage.pending)==len(e.snapshot.material_refs)
    with pytest.raises(ValueError):compute_coverage(db,'foreign',e.snapshot.id)

@pytest.mark.asyncio
async def test_empty_chunks_are_seen_and_cached_but_never_create_an_empty_profile(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env
    async def empty(request):return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"contact_id":"merchant-a"}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(empty)) as client:
        e.gateway.client=client
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    assert publish(db,e.snapshot,result,e.token).reason=='empty_result'
    assert db.execute("SELECT COUNT(*) FROM history_checkpoints WHERE state='succeeded'").fetchone()[0]>0
    assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==0

@pytest.mark.asyncio
async def test_merge_falls_back_to_bounded_field_units_without_recursive_summaries(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.profiles.contracts import Goods,Logistics
    e=history_env;calls=[]
    async def transport(request):
        wire=json.loads(request.content);p=json.loads(wire['messages'][-1]['content']);calls.append(p)
        unit=p['history_unit']
        if unit['phase']=='extract':
            span=unit['primary_spans'][0];ref={'message_id':span['message_id'],'revision':span['revision']}
            result={'contact_id':'merchant-a'}
            for group,kind in [('goods',Goods),('logistics',Logistics)]:
                result[group]={name:{'value':'收纳盒'*150,'state':'known','sources':[ref]} for name in kind.model_fields}
        else:result=p['candidates'][0]
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        e.gateway.client=client
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    merges=[p for p in calls if p['history_unit']['phase']=='merge']
    assert len(merges)==13 and all(p['history_unit']['field']!='all' for p in merges)
    assert result.goods.products.value=='收纳盒'*150 and result.logistics.price.value
    assert len(result.goods.products.sources)>1

@pytest.mark.asyncio
async def test_oversized_identical_field_is_assembled_without_another_model_call(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env;calls=[]
    async def transport(request):
        p=json.loads(json.loads(request.content)['messages'][-1]['content']);calls.append(p)
        span=p['history_unit']['primary_spans'][0]
        result={'contact_id':'merchant-a','goods':{'products':{'value':'收纳盒'*2400,'state':'known','sources':[{'message_id':span['message_id'],'revision':span['revision']}]}}}
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        e.gateway.client=client
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    assert all(p['history_unit']['phase']=='extract' for p in calls)
    assert len(result.goods.products.sources)>1
    assert publish(db,e.snapshot,result,e.token).version==1


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['role','model'])
async def test_semantic_versions_invalidate_checkpoints(db,history_env,change):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env
    async with e.client:
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        e.retry(change);e.calls.clear()
        if change=='role':
            with db:db.execute("UPDATE contacts SET role_version=role_version+1 WHERE account_id='acct-1' AND contact_id='merchant-a'")
        else:e.gateway.config=e.config.model_copy(update={'version':'changed-config'})
        e.snapshot=build_snapshot(db,e.snapshot.key,e.snapshot.cutoff,versions={**e.snapshot.versions,'model_config':e.gateway.config.version})
        await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert db.execute('SELECT COUNT(*) FROM history_run_units WHERE snapshot_id=? AND reused=1',(e.snapshot.id,)).fetchone()[0]==0
        assert e.calls

@pytest.mark.asyncio
async def test_failed_merge_retries_without_reextracting_successful_history(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env;fail=True;original=e.client._transport.handler
    async def transport(request):
        p=json.loads(json.loads(request.content)['messages'][-1]['content'])
        if fail and p.get('history_unit',{}).get('phase')=='merge':return httpx.Response(503)
        return await original(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        e.gateway.client=client
        with pytest.raises(ModelCallError):await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        e.retry('merge-retry');fail=False;e.calls.clear()
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert e.calls and all(p['history_unit']['phase']=='merge' for _,p in e.calls)
        assert publish(db,e.snapshot,result,e.token).version==1

@pytest.mark.asyncio
@pytest.mark.parametrize('corruption',['shorter_body','unknown_ref'])
async def test_coverage_checks_spans_against_frozen_material_not_only_declared_totals(db,history_env,corruption):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.analysis.coverage import compute_coverage
    e=history_env
    async with e.client:await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    row=db.execute("SELECT unit_id,primary_json FROM history_run_units WHERE snapshot_id=? AND phase='extract' ORDER BY ordinal LIMIT 1",(e.snapshot.id,)).fetchone()
    spans=json.loads(row['primary_json'])
    if corruption=='shorter_body':
        span=next(s for s in spans if s['total']>1);span['end']-=1;span['total']-=1
    else:spans.append({'message_id':'unknown-ref','revision':1,'start':0,'end':1,'total':1})
    with db:db.execute('UPDATE history_run_units SET primary_json=? WHERE snapshot_id=? AND unit_id=?',(json.dumps(spans),e.snapshot.id,row['unit_id']))
    assert not compute_coverage(db,'acct-1',e.snapshot.id).complete

@pytest.mark.asyncio
async def test_empty_merge_is_retryable_instead_of_a_successful_poisoned_checkpoint(db,history_env):
    from wechat_agent.analysis.history import WorkflowV2
    e=history_env;original=e.client._transport.handler;empty=True
    async def handler(request):
        p=json.loads(json.loads(request.content)['messages'][-1]['content'])
        if empty and p.get('history_unit',{}).get('phase')=='merge':
            return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"contact_id":"merchant-a"}'}}]})
        return await original(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        e.gateway.client=client
        with pytest.raises(ModelCallError) as error:await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert error.value.code=='history_merge_incomplete'
        assert db.execute("SELECT COUNT(*) FROM history_checkpoints WHERE phase='merge' AND state='succeeded'").fetchone()[0]==0
        empty=False;e.retry('repair-empty-merge');e.calls.clear()
        result=await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
        assert e.calls and all(p.get('history_unit',{}).get('phase')=='merge' for _,p in e.calls)
        assert publish(db,e.snapshot,result,e.token).version==1

@pytest.mark.asyncio
async def test_history_units_share_one_authorized_reader_and_do_not_rescan_progress_per_unit(db,history_env,monkeypatch):
    from wechat_agent.analysis.history import WorkflowV2
    from wechat_agent.context.reader import ContextReader
    e=history_env;constructed=[];scans=[];original=ContextReader.__init__
    def reader_init(self,*args,**kwargs):
        constructed.append(1);original(self,*args,**kwargs)
    monkeypatch.setattr(ContextReader,'__init__',reader_init)
    def trace(sql):
        if 'FROM history_run_units WHERE account_id=' in sql and 'unit_id=' not in sql:scans.append(sql)
    db.set_trace_callback(trace)
    async with e.client:await WorkflowV2(db,e.gateway).run(e.snapshot,None,e.token)
    db.set_trace_callback(None)
    assert len(constructed)==1
    assert len(scans)<=3
