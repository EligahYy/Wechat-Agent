import json
from contextlib import closing

import httpx
import pytest

from tests.factories import make_message, make_page
from tests.test_single_customer_flow import flow, open_existing_db, review, run_next
from wechat_agent.source.repository import archive_page


def request_body(key, **options):
    return {'action': 'sync_and_organize', 'scope': {'account_id': 'acct-1', 'contact_id': 'merchant-a'},
            'idempotency_key': key, 'options': {'text_strategy': 'relevance', **options}}


async def run(client, key, **options):
    response = client.post('/api/operations', json=request_body(key, **options))
    assert response.status_code == 202, response.text
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        return await run_next(conn, client.app.state.services)


def provider(client):
    payloads = []

    def transport(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        payloads.append(payload)
        result = {'contact_id': 'merchant-a'}
        if 'candidates' in payload:
            result = payload['candidates'][0]
        else:
            for row in payload['messages']:
                if row.get('evidence_allowed', True) and '确认报价 12 元' in row['body']:
                    result['logistics'] = {'price': {'value': '12 元', 'state': 'known', 'sources': [
                        {'message_id': row['message_id'], 'revision': row['revision']}
                    ]}}
                    break
                if row.get('evidence_allowed', True) and '确认货量 20 方' in row['body']:
                    result['goods'] = {'volume': {'value': '20 方', 'state': 'known', 'sources': [
                        {'message_id': row['message_id'], 'revision': row['revision']}
                    ]}}
        return httpx.Response(200, json={'model': 'synthetic', 'choices': [{
            'finish_reason': 'stop', 'message': {'content': json.dumps(result)}
        }]})

    client.app.state.services.model_transport = httpx.MockTransport(transport)
    return payloads


@pytest.mark.asyncio
async def test_high_extraction_and_low_only_append_preserve_published_version(flow):
    client, _, _ = flow
    review(client)
    calls = provider(client)
    entries = [
        make_message(message_id='fixture:group-1:2', sender_id='provider-p',
                     body='早上好', source_revision='quiet-provider'),
        make_message(message_id='noise', body='早上好'),
        make_message(message_id='price', body='确认报价 12 元'),
        make_message(message_id='other-price', sender_id='merchant-b', body='报价 16 元'),
    ]
    source = client.app.state.services.source
    source.pages['group-1'] = [make_page(entries)]
    first = await run(client, 'focused-first')
    assert first.state == 'succeeded', (first.error_code, first.report)
    assert first.counts['relevance_low'] >= 2
    assert first.counts['analysis_material_completed'] == first.counts['relevance_high']
    assert not {'noise', 'other-price'}.intersection(
        row['message_id'] for payload in calls for row in payload.get('messages', [])
    )
    url = f'/api/operations/{first.id}/relevance'
    result = client.get(url, params={'account_id': 'acct-1', 'level': 'low', 'day': '2026-11-11'})
    assert result.status_code == 200
    assert 'noise' in {item['message_id'] for item in result.json()['items']}
    assert client.get(url, params={'account_id': 'foreign'}).status_code == 403
    assert client.post('/api/operations', json=request_body('wrong-revision', relevance_review_refs=[
        {'message_id': 'noise', 'revision': 99},
    ])).status_code == 409

    calls.clear()
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        archive_page(conn, make_page([make_message(message_id='new-noise', body='节日快乐')]))
    second = await run(client, 'low-only')
    assert second.state == 'succeeded', second.error_code
    assert calls == []
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    assert profile['model_version'] == 1
    assert profile['profile_status'] != 'needs_update'


def test_relevance_requires_single_customer(flow):
    client, _, _ = flow
    body = request_body('wrong-scope')
    del body['scope']['contact_id']
    assert client.post('/api/operations', json=body).status_code == 422


@pytest.mark.asyncio
async def test_paired_history_sends_fewer_model_requests(flow):
    client, _, _ = flow
    review(client)
    calls = provider(client)
    source = client.app.state.services.source
    source.pages['group-1'] = [make_page([
        *[make_message(message_id=f'noise-{n}', body='早上好') for n in range(277)],
        make_message(message_id='tail', body='确认报价 12 元'),
    ])]
    from tests.test_single_customer_flow import sync
    full = await sync(client, 'full-baseline')
    assert full.state == 'succeeded', full.error_code
    baseline_calls = len(calls)
    baseline_bytes = sum(len(row['body'].encode()) for payload in calls for row in payload.get('messages', []))
    calls.clear()
    focused = await run(client, 'focused-comparison')
    assert focused.state == 'succeeded', focused.error_code
    assert focused.counts['relevance_total'] >= 278
    assert len(calls) * 2 <= baseline_calls
    assert sum(len(row['body'].encode()) for payload in calls for row in payload.get('messages', [])) * 2 <= baseline_bytes
    assert {row['message_id'] for payload in calls for row in payload.get('messages', [])} >= {'tail'}


@pytest.mark.asyncio
async def test_revoked_material_blocks_unchanged(flow):
    client, _, _ = flow
    review(client)
    calls = provider(client)
    source = client.app.state.services.source
    source.pages['group-1'] = [make_page([
        make_message(message_id='sole-price', body='确认报价 12 元'),
    ])]
    first = await run(client, 'before-revoke')
    assert first.state == 'succeeded', first.error_code
    calls.clear()
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        archive_page(conn, make_page([make_message(message_id='revoked', kind='revoke', body='撤回报价')]))
    second = await run(client, 'after-revoke')
    assert second.error_code == 'relevance_revocation_review'
    assert calls == []
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    assert profile['model_version'] == 1 and profile['profile_status'] == 'needs_update'


@pytest.mark.asyncio
async def test_pause_resumes_relevance_and_reuses_completed_extraction(flow, monkeypatch):
    from wechat_agent.analysis import runtime
    from wechat_agent.analysis.execution import ExecutionBudget
    from wechat_agent.analysis.history import WorkflowV5

    client, _, _ = flow
    review(client)
    calls = provider(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id='price', body='确认报价 12 元'),
    ])]
    original_pack = WorkflowV5.compact_unit
    monkeypatch.setattr(WorkflowV5, 'compact_unit', lambda *args: None)
    monkeypatch.setattr(runtime, 'ExecutionBudget', lambda: ExecutionBudget(max_calls=1))
    first = await run(client, 'focused-pause')
    monkeypatch.setattr(WorkflowV5, 'compact_unit', original_pack)
    assert first.error_code == 'analysis_budget_paused'
    sent = [payload['history_unit']['primary_spans'] for payload in calls]
    response = client.post('/api/operations', json={
        'action':'resume', 'account_id':'acct-1', 'operation_id':first.id,
    })
    assert response.status_code == 202
    assert response.json()['options']['text_strategy'] == 'relevance'
    duplicate = client.post('/api/operations', json={
        'action':'resume', 'account_id':'acct-1', 'operation_id':first.id,
    })
    assert duplicate.json()['id'] == response.json()['id']
    monkeypatch.setattr(runtime, 'ExecutionBudget', ExecutionBudget)
    calls.clear()
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        continued = await run_next(conn, client.app.state.services)
    assert continued.state == 'succeeded', continued.error_code
    assert continued.counts['analysis_chunks_reused'] >= 1
    assert not any(payload['history_unit'].get('primary_spans') in sent for payload in calls)


@pytest.mark.asyncio
async def test_context_only_timestamp_cannot_be_published(flow):
    from datetime import datetime

    client, _, _ = flow
    review(client)
    context_time = datetime.fromisoformat('2026-11-12T09:00:00+08:00')
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id='context', body='按上次那个', sent_at=context_time),
        make_message(message_id='price', body='确认报价 12 元', reply_to='context',
                     sent_at=datetime.fromisoformat('2026-11-12T09:01:00+08:00')),
    ])]
    seen_context = []

    def transport(request):
        data = json.loads(json.loads(request.content)['messages'][-1]['content'])
        result = {'contact_id': 'merchant-a'}
        if any(row['message_id'] == 'price' for row in data.get('messages', [])):
            seen_context.extend(row for row in data['messages'] if row['message_id'] == 'context')
            result['communication'] = {
                'summary': {'state':'known','value':'已确认报价','sources':[{'message_id':'price','revision':1}]},
                'last_business_at': context_time.isoformat(),
            }
        return httpx.Response(200, json={'model': 'synthetic', 'choices': [{
            'finish_reason': 'stop', 'message': {'content': json.dumps(result)}
        }]})

    client.app.state.services.model_transport = httpx.MockTransport(transport)
    result = await run(client, 'no-context-timestamp')
    assert result.state == 'succeeded', result.error_code
    assert seen_context and not seen_context[0]['evidence_allowed']
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    assert profile['effective']['communication']['last_business_at'] is None


@pytest.mark.parametrize('replace_price', [False, True])
@pytest.mark.asyncio
async def test_prior_quote_cannot_be_retained_after_reply_loses_attribution(flow, replace_price):
    client, _, _ = flow
    review(client)
    provider(client)
    source = client.app.state.services.source
    linked_quote = make_message(message_id='quote', sender_id='provider-p', reply_to='anchor', body='确认报价 12 元')
    source.pages['group-1'] = [make_page([
        make_message(message_id='anchor', body='询价德国'), linked_quote,
    ])]
    first = await run(client, 'with-anchor')
    assert first.state == 'succeeded', first.error_code
    source.pages['group-1'] = [make_page([
        make_message(message_id='anchor', body='早上好', source_revision='revision-2'),
        linked_quote,
        make_message(message_id='new', body='确认报价 12 元' if replace_price else '确认货量 20 方'),
    ])]
    final = await run(client, 'revised-anchor')
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    if replace_price:
        assert final.state == 'succeeded', final.error_code
        assert profile['effective']['logistics']['price']['sources'][0]['message_id'] == 'new'
    else:
        assert final.state == 'succeeded' and final.report.analysis_outcome == 'partial'
        assert profile['model_version'] == 2 and profile['profile_status'] == 'incomplete'
        assert profile['effective']['logistics']['price']['value'] is None
        assert profile['effective']['goods']['volume']['value'] == '20 方'


@pytest.mark.asyncio
async def test_37_high_messages_across_months_fit_one_request(flow):
    from datetime import datetime

    client, _, _ = flow
    review(client)
    calls = provider(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        *[make_message(message_id=f'greeting-{n}', body='早上好') for n in range(302)],
        *[make_message(message_id=f'price-{n}', body='确认报价 12 元',
                       sent_at=datetime.fromisoformat(f'2026-{8+n%3:02}-11T09:00:00+08:00'))
          for n in range(34)],
    ])]
    result = await run(client, 'short-relevance')
    assert result.state == 'succeeded', result.error_code
    assert result.counts['relevance_high'] == 37
    assert result.counts['analysis_material_completed'] == 37
    assert len(calls) == 1
    assert len(calls[0]['history_unit']['primary_spans']) == 37


@pytest.mark.asyncio
async def test_compact_output_truncation_splits_without_repeating_full_input(flow):
    client, _, _ = flow
    review(client)
    original_calls = provider(client)
    original = client.app.state.services.model_transport
    totals = []
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id=f'price-{index}', body='确认报价 12 元') for index in range(12)
    ])]

    async def transport(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        unit = payload.get('history_unit', {})
        if unit.get('packing') == 'compact' and not totals:
            totals.append(len(unit['primary_spans']))
            return httpx.Response(200, json={'model':'synthetic','choices':[{'finish_reason':'length'}]})
        return await original.handle_async_request(request)

    client.app.state.services.model_transport = httpx.MockTransport(transport)
    result = await run(client, 'compact-truncates')
    assert result.state == 'succeeded', result.error_code
    assert totals == [result.counts['relevance_high']]
    assert max(len(payload['history_unit'].get('primary_spans', [])) for payload in original_calls) < totals[0]
    assert result.counts['analysis_material_completed'] == totals[0]


@pytest.mark.asyncio
async def test_focused_timeout_stops_after_one_attempt_and_next_run_can_recover(flow):
    client, _, _ = flow
    review(client)
    client.app.state.services.source.pages['group-1'] = [make_page([make_message(message_id='price', body='确认报价 12 元')])]
    attempts = []
    def timeout(request):
        attempts.append(request)
        raise httpx.ReadTimeout("provider stalled", request=request)
    client.app.state.services.model_transport = httpx.MockTransport(timeout)
    first = await run(client, 'focused-timeout')
    assert first.error_code == 'model_timeout'
    assert len(attempts) == 1
    assert first.counts['analysis_refinements'] == 0
    assert first.counts['analysis_material_completed'] == 0
    assert first.counts['model_requests_started'] == first.counts['model_requests'] == 1
    calls = provider(client)
    recovered = await run(client, 'focused-timeout-retry')
    assert recovered.state == 'succeeded', recovered.error_code
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("conflicting", [False, True])
async def test_truncated_compact_pack_uses_two_balanced_children_and_combines_compatible_fields(flow, conflicting):
    client, _, _ = flow
    review(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id=f'price-{i}', body='确认报价 12 元或 13 元') for i in range(34)
    ])]
    sent = []
    def transport(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        sent.append(payload)
        if len(sent) == 1:
            choice = {'finish_reason': 'length'}
        elif 'messages' in payload:
            row = next((row for row in payload['messages'] if row['body'] == '确认报价 12 元或 13 元'), None)
            result = {'contact_id':'merchant-a'} if row is None else {'contact_id': 'merchant-a', 'logistics': {'price': {
                'state':'known', 'value':'13 元' if conflicting and len(sent) == 3 else '12 元',
                'sources':[{'message_id':row['source_alias'], 'revision':row['revision']}],
            }}}
            if row is not None:
                result['communication'] = {'last_business_at':row['sent_at']}
            choice = {'finish_reason':'stop', 'message':{'content':json.dumps(result)}}
        else:
            choice = {'finish_reason':'stop', 'message':{'content':json.dumps(payload['candidates'][0])}}
        return httpx.Response(200,json={'model':'synthetic','choices':[choice]})
    client.app.state.services.model_transport = httpx.MockTransport(transport)
    result = await run(client, 'focused-truncated-37')
    assert result.state == 'succeeded', result.error_code
    assert [len(p['history_unit'].get('primary_spans', [])) for p in sent] == [37, 18, 19]
    assert result.counts['analysis_material_completed'] == 37
    assert result.counts['model_requests_started'] == result.counts['model_requests'] == 3
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    fact = profile['effective']['logistics']['price']
    assert len(fact['sources']) == 2
    assert fact['value'] == ('12 元；13 元' if conflicting else '12 元')
    assert fact['state'] == ('uncertain' if conflicting else 'known')
    from datetime import datetime
    assert datetime.fromisoformat(profile['effective']['communication']['last_business_at']) == make_message().sent_at


@pytest.mark.asyncio
@pytest.mark.parametrize('ceiling,recovers', [(8192, False), (32768, True), (32768, False)])
async def test_reasoning_only_length_has_one_bounded_recovery_and_no_split(flow, ceiling, recovers):
    client, _, _ = flow
    version = 1
    if ceiling != 8192:
        base = client.get('/api/model', params={'account_id':'acct-1'}).json()
        config = {key:base[key] for key in ('account_id','endpoint','model_id','response_mode','context_tokens')}
        assert client.put('/api/model',json={**config,'max_output_tokens':ceiling,'expected_version':1}).status_code == 200
        version = 2
        assert client.post('/api/model/check',json={'account_id':'acct-1','expected_version':version}).status_code == 200
    assert client.post('/api/model/budget-review',json={'account_id':'acct-1','expected_version':version,
        'reference':'https://docs.example/model-budget','acknowledged':True}).status_code == 200
    client.app.state.services.source.pages['group-1'] = [make_page([make_message(message_id='price',body='确认报价 12 元')])]
    provider(client)
    original = client.app.state.services.model_transport
    limits = []
    async def transport(request):
        limit = json.loads(request.content)['max_tokens']
        limits.append(limit)
        if recovers and len(limits) == 2:
            return await original.handle_async_request(request)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length','message':{'content':''}}],
            'usage':{'completion_tokens':limit,'completion_tokens_details':{'reasoning_tokens':limit}}})
    client.app.state.services.model_transport = httpx.MockTransport(transport)
    result = await run(client, 'reasoning-only')
    assert limits == ([8192, 16384] if ceiling > 8192 else [8192])
    assert result.counts['analysis_refinements'] == 0
    if recovers:
        assert result.state == 'succeeded'
    else:
        assert result.error_code == 'model_reasoning_output_exhausted'


@pytest.mark.asyncio
@pytest.mark.parametrize('resume,old_timeout', [(True,False),(True,True),(False,False)])
async def test_existing_split_is_preserved_on_continue_and_replanned_for_new_run(flow, monkeypatch, resume, old_timeout):
    from wechat_agent.analysis import runtime
    from wechat_agent.analysis.execution import ExecutionBudget
    from wechat_agent.analysis.history import WorkflowV5

    client, _, _ = flow
    review(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id=f'price-{i}', body='确认报价 12 元') for i in range(34)
    ])]
    calls = provider(client)
    original = client.app.state.services.model_transport
    async def transport(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        if len(payload['history_unit'].get('primary_spans', [])) == 37:
            return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'length'}]})
        return await original.handle_async_request(request)
    client.app.state.services.model_transport = httpx.MockTransport(transport)
    # Reproduce the previous version's successful first child followed by a pause.
    pack = WorkflowV5.pack_rows
    monkeypatch.setattr(WorkflowV5, 'pack_rows', lambda self, rows, *args:
                        pack(self, rows, *args) if len(rows) == 37 else None)
    monkeypatch.setattr(runtime, 'ExecutionBudget', lambda:ExecutionBudget(max_calls=2))
    paused = await run(client, 'old-refinement')
    assert paused.error_code == 'analysis_budget_paused'
    assert paused.counts['analysis_chunks_completed'] == 1
    if old_timeout:
        with closing(open_existing_db(client.app.state.database_path)) as conn:
            conn.execute("UPDATE history_checkpoints SET error_code='model_timeout' WHERE error_code='output_truncated'")
            conn.commit()
        async def reject_parent(request):
            payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
            assert len(payload['history_unit'].get('primary_spans', [])) != 37
            return await original.handle_async_request(request)
        client.app.state.services.model_transport = httpx.MockTransport(reject_parent)
    monkeypatch.setattr(WorkflowV5, 'pack_rows', pack)
    monkeypatch.setattr(runtime, 'ExecutionBudget', ExecutionBudget)
    calls.clear()
    if resume:
        response = client.post('/api/operations', json={'action':'resume','account_id':'acct-1','operation_id':paused.id})
        assert response.status_code == 202
        with closing(open_existing_db(client.app.state.database_path)) as conn:
            result = await run_next(conn, client.app.state.services)
        assert result.counts['analysis_chunks_reused'] >= 1
    else:
        result = await run(client, 'fresh-refinement')
        assert [len(p['history_unit']['primary_spans']) for p in calls] == [18, 19]
    assert result.state == 'succeeded'
    assert result.counts['analysis_material_completed'] == 37


@pytest.mark.asyncio
@pytest.mark.parametrize('archive_change', [None, 'message', 'cursor'])
async def test_continue_after_timeout_renews_quota_and_only_syncs_changed_archive(flow, monkeypatch, archive_change):
    client, _, _ = flow
    review(client)
    client.app.state.services.source.pages['group-1'] = [
        make_page([make_message(message_id='price', body='确认报价 12 元')])
    ]
    def timeout(request):
        raise httpx.ReadTimeout('provider stalled', request=request)
    client.app.state.services.model_transport = httpx.MockTransport(timeout)
    stalled = await run(client, 'repeat-timeout')
    assert stalled.error_code == 'model_timeout'
    forged = client.post('/api/operations', json=request_body('resume:' + stalled.id, from_start=True))
    assert forged.status_code == 422
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        conn.execute('UPDATE history_checkpoints SET requests=6')
        conn.commit()
        if archive_change == 'message':
            archive_page(conn, make_page([make_message(message_id='new-price', body='确认报价 12 元')]))
        elif archive_change == 'cursor':
            archive_page(conn, make_page([], complete=False, next_cursor='page:1'))
            client.app.state.services.source.pages['group-1'].append(make_page([]))
    from wechat_agent.operations import worker
    real_sync = worker.sync_scope
    synced = []
    async def sync_scope(*args, **kwargs):
        synced.append(True)
        return await real_sync(*args, **kwargs)
    monkeypatch.setattr(worker, 'sync_scope', sync_scope)
    calls = provider(client)
    response = client.post('/api/operations', json={'action':'resume','account_id':'acct-1','operation_id':stalled.id})
    assert response.status_code == 202, response.text
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        result = await run_next(conn, client.app.state.services)
    assert result.state == 'succeeded', result.error_code
    assert bool(synced) == bool(archive_change)
    assert bool(result.counts.get('source_checkpoint_reused')) != bool(archive_change)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_high_value_keeps_verified_fields_when_other_reference_is_invalid(flow):
    client, _, _ = flow
    review(client)
    client.app.state.services.source.pages['group-1'] = [
        make_page([make_message(message_id='price', body='确认报价 12 元')])
    ]
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) != 1:
            raise httpx.ReadTimeout('repair would stall', request=request)
        fact = {'value':'12 元','state':'known','sources':[{'message_id':'price','revision':1}]}
        bad = {**fact, 'sources':[{'message_id':'missing','revision':1}]}
        return httpx.Response(200,json={'model':'synthetic','choices':[{
            'finish_reason':'stop','message':{'content':json.dumps({
                'contact_id':'merchant-a','logistics':{'price':fact,'concerns':bad}
            })}
        }]})
    client.app.state.services.model_transport = httpx.MockTransport(respond)
    result = await run(client, 'one-field-invalid')
    assert result.state == 'succeeded', result.error_code
    assert result.report.analysis_outcome == 'partial'
    assert len(calls) == 1
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    assert profile['effective']['logistics']['price']['value'] == '12 元'
    assert profile['effective']['logistics']['concerns']['value'] is None


@pytest.mark.asyncio
async def test_prior_batch_needing_review_does_not_block_new_fields(flow):
    from wechat_agent.profiles.contracts import ShipmentCandidate
    from wechat_agent.profiles.shipments import save_shipments
    from wechat_agent.source.contracts import ContactKey
    from wechat_agent.source.repository import transaction

    client, _, _ = flow
    review(client)
    provider(client)
    older = make_message(message_id='previous-batch', body='已安排备货')
    current = make_message(message_id='price', body='确认报价 12 元')
    client.app.state.services.source.pages['group-1'] = [make_page([current])]
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        archive_page(conn, make_page([older]))
        with transaction(conn):
            batches, _ = save_shipments(conn, ContactKey(account_id='acct-1', contact_id='merchant-a'), [
                ShipmentCandidate(candidate_key='old-batch', stage='备货', sources=[
                    {'message_id':'previous-batch','revision':1}
                ])
            ])
    replacement = older.model_copy(update={'source_revision':'v2','body':'早上好'})
    client.app.state.services.source.pages['group-1'] = [make_page([replacement, current])]
    result = await run(client, 'new-price-old-batch')
    assert result.state == 'succeeded'
    assert result.report.analysis_outcome == 'partial'
    assert any(i.code == 'prior_shipment_needs_review' for c in result.report.contacts for i in c.issues)
    profile = client.get('/api/contacts/merchant-a/profile', params={'account_id':'acct-1'}).json()
    assert profile['effective']['logistics']['price']['value'] == '12 元'
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        old = conn.execute('SELECT payload_json FROM shipments WHERE shipment_id=?', (batches[0].existing_id,)).fetchone()
        assert ShipmentCandidate.model_validate_json(old[0]) == batches[0]
