import json
from contextlib import closing
from tests.test_single_customer_flow import open_existing_db
import httpx
import pytest
from tests.test_single_customer_flow import flow,sync
from tests.factories import make_message,make_page


def prepare(client, *, context_tokens=24000):
    changed=client.put('/api/model',json={'account_id':'acct-1','expected_version':1,'endpoint':'https://synthetic.example/chat/completions','model_id':'synthetic','response_mode':'json_object','context_tokens':context_tokens,'max_output_tokens':1024})
    assert changed.status_code==200
    assert client.post('/api/model/check',json={'account_id':'acct-1','expected_version':2}).status_code==200
    assert client.post('/api/model/budget-review',json={'account_id':'acct-1','expected_version':2,'reference':'https://docs.example/budget','acknowledged':True}).status_code==200
    client.app.state.services.source.pages['group-1']=[make_page([make_message(message_id=f'history-{i:02}',body='收纳盒12方 '+('历史语境资料 '*150)) for i in range(12)])]
    seen=[];state={'fail':False}
    def transport(request):
        p=json.loads(json.loads(request.content)['messages'][-1]['content']);seen.append(p)
        unit=p.get('history_unit',{})
        if state['fail'] and any(s['message_id']=='history-05' for s in unit.get('primary_spans',[])):return httpx.Response(state.get('status', 503), headers=state.get('headers'))
        if unit.get('phase')=='merge':candidate=p['candidates'][0]
        else:
            messages=p.get('messages',[]);row=next((m for m in messages if '12' in m['body'] and m['kind']=='text'),None)
            candidate={'contact_id':'merchant-a','goods':{'volume':{'state':'known','value':'12方','sources':[{'message_id':row['message_id'],'revision':row['revision']}]}}} if row else {'contact_id':'merchant-a'}
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':json.dumps(candidate)}}]})
    client.app.state.services.model_transport=httpx.MockTransport(transport)
    return seen,state

@pytest.mark.asyncio
async def test_production_large_history_publishes_and_keeps_progress_then_skips_unchanged(flow):
    client,_,_=flow;seen,_=prepare(client)
    op=await sync(client,'history')
    assert op.report.analysis_outcome=='updated' and len(seen)>2
    assert op.counts['analysis_chunks_total']>1
    assert op.counts['analysis_chunks_completed']==op.counts['analysis_chunks_total']
    assert op.counts['analysis_merge_completed']>0
    assert op.counts['analysis_material_completed']==op.counts['analysis_material_total']
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        count_before = conn.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
    count=len(seen);again=await sync(client,'history-unchanged')
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == count_before
    assert again.report.analysis_outcome=='unchanged' and len(seen)==count

@pytest.mark.parametrize('status,legacy', [(429, False), (503, False), (503, True)])
@pytest.mark.asyncio
async def test_production_retry_reuses_good_chunks_instead_of_repaying_for_them(flow, monkeypatch, status, legacy):
    from wechat_agent.model import gateway
    clock = [1000.]
    monkeypatch.setattr(gateway, "time", lambda: clock[0])
    client,_,_=flow;seen,state=prepare(client);state.update(fail=True, status=status, headers={'Retry-After': '0'})
    failed=await sync(client,'failure')
    assert failed.source_state=='succeeded' and failed.state=='failed'
    assert failed.counts.get('analysis_chunks_completed',0)>0
    assert failed.counts.get('analysis_chunks_failed',0)>0
    clock[0] += 6
    failed_again = await sync(client, 'failure-again')
    assert failed_again.state == 'failed'
    state['fail']=False;seen.clear()
    if legacy:
        # Recreate the durable evidence schema 18 left after six failures.
        with closing(open_existing_db(client.app.state.database_path)) as conn, conn:
            conn.execute("UPDATE history_checkpoints SET requests=6 WHERE error_code='model_temporary_error'")
            conn.execute('DELETE FROM history_retry_windows')
            assert conn.execute("SELECT COUNT(*) FROM model_calls WHERE status='model_temporary_error'").fetchone()[0] == 6
    else:
        cooling = await sync(client, 'cooling')
        assert cooling.error_code == 'model_retry_cooling_down'
        assert seen == []
        clock[0] += 6
    done=await sync(client,'recovered')
    assert done.report.analysis_outcome=='updated', done.error_code
    assert done.counts['analysis_chunks_reused']>0
    assert done.counts['analysis_chunks_completed']==done.counts['analysis_chunks_total']


@pytest.mark.asyncio
async def test_resume_repacks_untouched_history_without_repaying_completed_units(flow, monkeypatch):
    from wechat_agent.analysis import runtime
    from wechat_agent.analysis.execution import ExecutionBudget
    from wechat_agent.analysis.history import WorkflowV4
    from wechat_agent.context.chunks import plan_chunks
    from tests.test_single_customer_flow import run_next

    client, _, _ = flow
    seen, _ = prepare(client, context_tokens=1_048_000)
    pages = [make_page([
        make_message(message_id=f'quote-{index:03}', body='确认12方，核对价格及到货时间。' * 4)
        for index in range(278)
    ])]
    client.app.state.services.source.pages['group-1'] = pages
    current = WorkflowV4.material_window

    async def legacy(self, snapshot, room, window, rows, full_history, planned, extraction, target):
        with self.conn:
            self.conn.execute(
                """INSERT INTO analysis_workload_plans VALUES(?,?,?,?,?,'extract',8000)
                   ON CONFLICT DO NOTHING""",
                (snapshot.key.account_id, snapshot.key.contact_id, self.gateway.config.version, room, window),
            )
        return plan_chunks(rows, planned, self.gateway.config, soft_input_target=8000, context_messages=full_history)

    monkeypatch.setattr(WorkflowV4, 'material_window', legacy)
    monkeypatch.setattr(runtime, 'ExecutionBudget', lambda: ExecutionBudget(max_calls=4))
    paused = await sync(client, 'before-packing')
    assert paused.error_code == 'analysis_budget_paused'
    assert paused.counts['analysis_chunks_total'] > 30
    completed = {span['message_id'] for row in seen for span in row.get('history_unit', {}).get('primary_spans', [])}

    monkeypatch.setattr(WorkflowV4, 'material_window', current)
    monkeypatch.setattr(runtime, 'ExecutionBudget', ExecutionBudget)
    seen.clear()
    queued = client.post('/api/operations', json={'action': 'resume', 'account_id': 'acct-1', 'operation_id': paused.id})
    assert queued.status_code == 202
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        result = await run_next(conn, client.app.state.services)

    assert result.state == 'succeeded', result.error_code
    assert result.counts['analysis_chunks_reused'] == 4
    assert len(seen) < 10
    assert result.counts['analysis_material_completed'] == result.counts['analysis_material_total']
    assert not completed.intersection(
        span['message_id'] for row in seen for span in row.get('history_unit', {}).get('primary_spans', [])
    )
