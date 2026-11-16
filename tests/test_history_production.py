import json
import httpx
import pytest
from tests.test_single_customer_flow import flow,sync
from tests.factories import make_message,make_page


def prepare(client):
    changed=client.put('/api/model',json={'account_id':'acct-1','expected_version':1,'endpoint':'https://synthetic.example/chat/completions','model_id':'synthetic','response_mode':'json_object','context_tokens':24000,'max_output_tokens':1024})
    assert changed.status_code==200
    assert client.post('/api/model/check',json={'account_id':'acct-1','expected_version':2}).status_code==200
    assert client.post('/api/model/budget-review',json={'account_id':'acct-1','expected_version':2,'reference':'https://docs.example/budget','acknowledged':True}).status_code==200
    client.app.state.services.source.pages['group-1']=[make_page([make_message(message_id=f'history-{i:02}',body='收纳盒12方 '+('历史语境资料 '*150)) for i in range(12)])]
    seen=[];state={'fail':False}
    def transport(request):
        p=json.loads(json.loads(request.content)['messages'][-1]['content']);seen.append(p)
        unit=p.get('history_unit',{})
        if state['fail'] and any(s['message_id']=='history-05' for s in unit.get('primary_spans',[])):return httpx.Response(503)
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
    count=len(seen);again=await sync(client,'history-unchanged')
    assert again.report.analysis_outcome=='unchanged' and len(seen)==count

@pytest.mark.asyncio
async def test_production_retry_reuses_good_chunks_instead_of_repaying_for_them(flow):
    client,_,_=flow;seen,state=prepare(client);state['fail']=True
    failed=await sync(client,'failure')
    assert failed.source_state=='succeeded' and failed.state=='failed'
    assert failed.counts.get('analysis_chunks_completed',0)>0
    assert failed.counts.get('analysis_chunks_failed',0)>0
    state['fail']=False;seen.clear()
    done=await sync(client,'recovered')
    assert done.report.analysis_outcome=='updated'
    assert done.counts['analysis_chunks_reused']>0
    assert done.counts['analysis_chunks_completed']==done.counts['analysis_chunks_total']
