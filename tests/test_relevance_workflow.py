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

    client, _, _ = flow
    review(client)
    calls = provider(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id='price', body='确认报价 12 元'),
    ])]
    monkeypatch.setattr(runtime, 'ExecutionBudget', lambda: ExecutionBudget(max_calls=1))
    first = await run(client, 'focused-pause')
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
        assert final.error_code == 'retained_evidence_unavailable'
        assert profile['model_version'] == 1 and profile['profile_status'] == 'needs_update'
