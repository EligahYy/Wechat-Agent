import json

import pytest

from tests.test_history_production import prepare
from tests.test_single_customer_flow import flow, sync
from wechat_agent.analysis.adaptive import WorkPolicy, observe_attempt, pinned_target
from wechat_agent.analysis.citations import build_aliases, resolve_aliases, isolate_invalid_fields
from wechat_agent.analysis.execution import ExecutionBudget
from wechat_agent.analysis.reduction import combine_field, references
from wechat_agent.profiles.contracts import AnalysisResult
from wechat_agent.profiles.issues import classify_issues


def fact(value, identifier='one'):
    return {'state': 'known', 'value': value, 'sources': [{'message_id': identifier, 'revision': 1}]}


def candidate(value, identifier='one'):
    return {'contact_id': 'merchant-a', 'logistics': {'price': fact(value, identifier)}}


def test_alias_keeps_original_revision_and_prioritizes_valid_siblings():
    aliases = build_aliases({('one', 1), ('two', 1)})
    alias = next(key for key, ref in aliases.items() if ref == ('one', 1))
    other = build_aliases({('one', 2)})
    assert alias not in other
    result = resolve_aliases({
        **candidate('报价100元', alias),
        'goods': {'volume': fact('99方', 'invented')},
    }, aliases)
    parsed = isolate_invalid_fields(AnalysisResult.model_validate(result), {('one', 1), ('two', 1)})
    assert parsed.logistics.price.sources[0].message_id == 'one'
    assert parsed.goods.volume.value is None
    assert parsed.gaps == ['goods.volume:source_outside_unit']
    changed = candidate('报价100元', alias)
    changed['logistics']['price']['sources'][0]['revision'] = 2
    assert resolve_aliases(changed, aliases) == changed


def test_field_conflicts_keep_values_and_all_source_revisions():
    result = combine_field('logistics.price', [candidate('报价100元'), candidate('报价200元', 'two')], 'merchant-a')
    assert result.logistics.price.state == 'uncertain'
    assert result.logistics.price.value == '报价100元；报价200元'
    assert references(result) == {('one', 1), ('two', 1)}
    assert result.gaps == ['logistics.price:conflicting_candidates']


def test_issue_policy_groups_attachments_and_distinguishes_business_uncertainty():
    issues = classify_issues([
        'attachment_not_processed:first', 'attachment_not_processed:second',
        'attachment_not_processed:third', 'attachment_not_processed:fourth',
        'communication.summary:number_not_supported', 'communication.tags:summary_missing',
        '事实尚未明确：付款方式', 'unknown_legacy',
    ])
    by_code = {issue.code: issue for issue in issues}
    assert by_code['attachment_not_processed'].count == 4
    assert by_code['number_not_supported'].field_path == 'communication.summary'
    assert by_code['business_uncertainty'].severity == 'business_uncertainty'
    assert by_code['analysis_review_required'].detail == 'unknown_legacy'
    assert 'summary_missing' not in by_code


def test_feedback_grows_new_windows_but_keeps_persisted_targets(db):
    db.execute("INSERT INTO accounts(account_id) VALUES('a')")
    db.commit()
    assert pinned_target(db, 'a', 'c', 'v', 'room', '2026-10') == 24_000
    with db:
        for _ in range(2):
            observe_attempt(db, 'a', 'v', 'extract', 'succeeded', 10_000, {'completion_tokens': 100}, 400)
    assert pinned_target(db, 'a', 'c', 'v', 'room', '2026-10') == 24_000
    assert pinned_target(db, 'a', 'c', 'v', 'room', '2026-11') == 30_000
    with db:
        observe_attempt(db, 'a', 'v', 'extract', 'rate_limited', 0, {}, 400)
        observe_attempt(db, 'a', 'v', 'extract', 'model_timeout', 90_000, {}, 400)
    assert pinned_target(db, 'a', 'c', 'v', 'room', '2026-12') == 15_000
    assert pinned_target(db, 'a', 'c', 'new-model', 'room', '2026-12') == WorkPolicy.target


@pytest.mark.asyncio
async def test_budget_pauses_and_resume_reuses_validated_units(flow, monkeypatch):
    from wechat_agent.analysis import runtime
    from contextlib import closing
    from tests.test_single_customer_flow import open_existing_db, run_next

    client, _, _ = flow
    seen, _ = prepare(client)
    monkeypatch.setattr(runtime, 'ExecutionBudget', lambda: ExecutionBudget(max_calls=2))
    first = await sync(client, 'pause-test')
    assert first.error_code == 'analysis_budget_paused'
    assert first.available_actions == ['resume']
    assert len(seen) == first.counts['model_requests'] == 2
    assert first.counts['timing_source_ms'] >= 0 and first.counts['timing_model_extract_ms'] >= 0
    data = {'action': 'resume', 'operation_id': first.id, 'account_id': 'acct-1'}
    queued = client.post('/api/operations', json=data)
    assert queued.status_code == 202
    duplicate = client.post('/api/operations', json=data)
    assert duplicate.json()['id'] == queued.json()['id']
    monkeypatch.setattr(runtime, 'ExecutionBudget', ExecutionBudget)
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        continued = await run_next(conn, client.app.state.services)
        attempts = conn.execute('SELECT requests FROM analysis_execution WHERE operation_id=?', (first.id,)).fetchone()[0]
        assert attempts == 2
        assert conn.execute('SELECT COUNT(*) FROM model_calls WHERE elapsed_ms IS NOT NULL').fetchone()[0] == len(seen)
    assert continued.state == 'succeeded' and continued.counts['analysis_chunks_reused'] >= 2
    assert client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()['model_version'] == 1


@pytest.mark.parametrize('count', [1, 80, 81, 1_000, 10_000])
def test_planning_matrix_covers_each_primary_message_once(count):
    from tests.test_context_chunks import config, message, request
    from wechat_agent.context.chunks import plan_chunks

    rows = [message(index, body='业务消息' if index == count-1 else '资料', room=str(index//100))
            for index in range(count)]
    chunks = plan_chunks(rows, request, config(128_000), soft_input_target=24_000)
    covered = [span.message_id for chunk in chunks for span in chunk.spans]
    assert len(covered) == count
    assert set(covered) == {row['message_id'] for row in rows}
    assert all(chunk.budget.fits for chunk in chunks)


@pytest.mark.asyncio
async def test_append_reuses_closed_extraction_after_published_profile_changes(flow):
    from tests.factories import make_message, make_page

    client, _, _ = flow
    seen, _ = prepare(client)
    first = await sync(client, 'before-append')
    assert first.state == 'succeeded'
    seen.clear()

    source = client.app.state.services.source
    prior = source.pages['group-1'][0]
    source.pages['group-1'] = [make_page([
        *prior.records, make_message(message_id='history-99', body='仍然是收纳盒 12方'),
    ])]
    appended = await sync(client, 'after-append')
    assert appended.state == 'succeeded'
    assert appended.counts['analysis_chunks_reused'] > 0
    assert len(seen) < first.counts['model_requests']
    assert appended.counts['analysis_material_total'] == first.counts['analysis_material_total'] + 1


def test_thousand_conflicting_quotes_use_evidence_union_with_bounded_display():
    values = [candidate(f'报价{index}元', str(index)) for index in range(1000)]
    result = combine_field('logistics.price', values, 'merchant-a')
    assert result.logistics.price.state == 'uncertain'
    assert len(result.logistics.price.value) <= 16_000
    assert references(result) == {(str(index), 1) for index in range(1000)}


def test_sparse_acknowledgement_cannot_claim_unread_or_duplicate_material():
    from wechat_agent.analysis.extraction import normalize_extraction
    from wechat_agent.model.contracts import ModelCallError

    for identifiers in (['one', 'one'], ['one', 'other'], []):
        with pytest.raises(ModelCallError, match='模型请求未完成') as error:
            normalize_extraction({'processed_primary_ids': identifiers}, {'one'}, {})
        assert error.value.code == 'history_coverage_incomplete'
    assert normalize_extraction({'processed_primary_ids': ['@one']}, {'one'}, {'@one': ('one', 1)}) == {}


def test_reduction_cannot_certify_distinct_values_with_shared_sources():
    from wechat_agent.analysis.reduction import preserves_candidate

    first = AnalysisResult.model_validate(candidate('报价100元'))
    second = AnalysisResult.model_validate(candidate('报价200元'))
    assert references(first) == references(second)
    assert not preserves_candidate(first, second)


def test_oversized_conflicts_cannot_overwrite_facts_with_a_placeholder():
    from wechat_agent.model.contracts import ModelCallError

    with pytest.raises(ModelCallError) as error:
        combine_field('logistics.price', [candidate('甲'*9000), candidate('乙'*9000, 'two')], 'merchant-a')
    assert error.value.code == 'history_merge_unit_too_large'


def test_reduction_cannot_swap_evidence_between_shipment_fields():
    from wechat_agent.analysis.reduction import preserves_candidate

    shipment = {
        'candidate_key': 'batch-one', 'stage': '备货',
        'goods': [fact('收纳盒', 'one')], 'logistics': [fact('海运', 'two')],
    }
    original = AnalysisResult(contact_id='merchant-a', shipments=[shipment])
    swapped = AnalysisResult(contact_id='merchant-a', shipments=[{
        **shipment, 'goods': [fact('收纳盒', 'two')], 'logistics': [fact('海运', 'one')],
    }])
    assert references(original) == references(swapped)
    assert not preserves_candidate(swapped, original)


@pytest.mark.asyncio
async def test_unchanged_uncertain_discovery_is_not_repaid_on_continuation(db, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from tests.test_business_discovery import NOW, prepare
    from wechat_agent.analysis import runner
    from wechat_agent.discovery.contracts import DiscoveryResult
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.service import create_operation, resume_operation
    from wechat_agent.operations.worker import _claim

    prepare(db)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)
    class Strategy:
        gateway = SimpleNamespace(config=SimpleNamespace(version='test-model-v1'))
        calls = []
        async def classify(self, snapshot, token):
            self.calls.append(snapshot.key.contact_id)
            own = next(ref for ref in snapshot.material_refs if ref.message_id == 'demand')
            return DiscoveryResult(contact_id=snapshot.key.contact_id, intent='uncertain', sources=[own])
    monkeypatch.setattr(runner, 'datetime', Clock)
    scope = OperationScope(account_id='acct-1', contact_id='merchant-a')
    create_operation(db, 'sync_and_organize', scope, 'discover-first')
    operation, owner, _ = _claim(db, 'acct-1')
    strategy = Strategy()
    await runner.discover(db, operation, owner, strategy)
    with db:
        db.execute("UPDATE operations SET state='failed',error_code='analysis_budget_paused' WHERE id=?", (operation.id,))
    resume_operation(db, 'acct-1', operation.id)
    continued, new_owner, _ = _claim(db, 'acct-1')
    await runner.discover(db, continued, new_owner, strategy)
    assert strategy.calls == ['merchant-a']


def test_local_communication_merge_preserves_latest_status():
    from wechat_agent.analysis.reduction import combine_field
    candidates = [
        {'contact_id': 'a', 'communication': {
            'summary': {'state': 'known', 'value': value, 'sources': [{'message_id': value, 'revision': 1}]},
            'tags': [tag], 'last_business_at': stamp,
        }}
        for value, tag, stamp in [
            ('报价', '询价中', '2026-11-18T12:00:00Z'),
            ('初次沟通', '初步沟通', '2026-11-17T12:00:00Z'),
        ]
    ]
    single = combine_field('communication', candidates[:1], 'a').communication
    assert single.summary.state == 'known'
    assert single.tags == ['询价中']
    result = combine_field('communication', candidates, 'a').communication
    assert result.tags == ['询价中']
    assert result.last_business_at == single.last_business_at
    assert {ref.message_id for ref in result.summary.sources} == {'报价', '初次沟通'}


@pytest.mark.parametrize('pause', [False, True])
@pytest.mark.asyncio
async def test_worker_keeps_two_distinct_quotes_when_model_merge_drops_one(flow, monkeypatch, pause):
    import httpx
    from contextlib import closing
    from tests.factories import make_message, make_page
    from tests.test_single_customer_flow import open_existing_db
    from wechat_agent.context.contracts import ContextSnapshot
    from wechat_agent.context.reader import ContextReader

    client, _, _ = flow
    prepare(client)
    client.app.state.services.source.pages['group-1'] = [make_page([
        make_message(message_id=f'quote-{i}', body=f'报价{12 + 3*i}元 ' + '报价说明 ' * 240)
        for i in range(2)
    ])]
    calls = []
    reserve = ExecutionBudget.reserve
    paused = False

    def pause_after_bad_merge(budget, conn, account, operation):
        nonlocal paused
        if pause and not paused and any(len(p.get('candidates', [])) == 2 for p in calls):
            paused = True
            from wechat_agent.model.contracts import ModelCallError
            raise ModelCallError('analysis_budget_paused')
        reserve(budget, conn, account, operation)

    monkeypatch.setattr(ExecutionBudget, 'reserve', pause_after_bad_merge)

    def transport(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(payload)
        if 'candidates' in payload:
            result = payload['candidates'][0]
        else:
            seen = {span['message_id'] for span in payload.get('history_unit', {}).get('primary_spans', [])}
            if not seen:
                seen = {row['message_id'] for row in payload['messages']}
                if {'quote-0', 'quote-1'} <= seen:
                    return httpx.Response(200, json={'model': 'synthetic', 'choices': [{'finish_reason': 'length'}]})
            result = {'contact_id': 'merchant-a'}
            for i in range(2):
                if f'quote-{i}' in seen:
                    result = candidate(f'报价{12 + 3*i}元', f'quote-{i}')
                    break
        return httpx.Response(200, json={'model': 'synthetic', 'choices': [{
            'finish_reason': 'stop', 'message': {'content': json.dumps(result)}
        }]})

    client.app.state.services.model_transport = httpx.MockTransport(transport)
    run = await sync(client, 'quotes')
    if pause:
        assert run.error_code == 'analysis_budget_paused'
        run = await sync(client, 'resume-quotes')
    assert run.state == 'succeeded', run.error_code
    assert sum(payload.get('history_unit', {}).get('field') == 'all' for payload in calls) == 1
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        version = conn.execute('SELECT * FROM profile_versions').fetchone()
        snapshot = ContextSnapshot.model_validate_json(conn.execute(
            'SELECT manifest_json FROM snapshots WHERE snapshot_id=?', (version['snapshot_id'],),
        ).fetchone()[0])
        ledger = conn.execute('SELECT output_json FROM history_reduction_nodes').fetchall()
        merged = [AnalysisResult.model_validate_json(row[0]) for row in ledger]
        price = AnalysisResult.model_validate_json(version['result_json']).logistics.price
        assert price.value == '报价12元；报价15元'
        assert any(result.logistics.price == price for result in merged)
        reader = ContextReader(conn, snapshot)
        assert all(str(12 + 3*i) in reader.resolve(ref)['body'] for i, ref in enumerate(price.sources))
