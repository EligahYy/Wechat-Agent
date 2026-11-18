import json

import pytest

from tests.test_history_workflow import history_env
from wechat_agent.analysis.coverage import compute_coverage
from wechat_agent.analysis.history import WorkflowV2


@pytest.mark.asyncio
async def test_large_window_does_not_send_all_history_in_one_call(db, history_env):
    e = history_env
    capabilities = e.config.capabilities.model_copy(update={'context_tokens': 1_048_000})
    e.gateway.config = e.config.model_copy(update={'capabilities': capabilities})

    async with e.client:
        await WorkflowV2(db, e.gateway).run(e.snapshot, None, e.token)
        extracts = [p for _, p in e.calls if 'messages' in p]
        assert len(extracts) > 1
        assert all(len(p['history_unit']['primary_spans']) < len(e.snapshot.material_refs) for p in extracts)
        assert compute_coverage(db, 'acct-1', e.snapshot.id).complete

        e.retry('adaptive-retry')
        e.calls.clear()
        await WorkflowV2(db, e.gateway).run(e.snapshot, None, e.token)
        assert e.calls == []


def test_initial_output_changes_with_request_material(history_env):
    e = history_env
    capabilities = e.config.capabilities.model_copy(
        update={'context_tokens': 1_048_000, 'max_output_tokens': 32_000}
    )
    e.gateway.config = e.config.model_copy(update={'capabilities': capabilities})
    workflow = WorkflowV2(e.gateway.conn, e.gateway)
    small = workflow.request(e.snapshot, {'messages': [{'body': '收纳盒12方'}]}, 'rules')
    dense = workflow.request(e.snapshot, {'messages': [{'body': '订单资料' * 2000}]}, 'rules')
    assert 0 < small.output_tokens < dense.output_tokens <= 8192
    assert json.loads(small.messages[-1].content)['messages'][0]['body'] == '收纳盒12方'


def test_soft_target_keeps_required_reply_and_splits_long_original():
    from tests.test_context_chunks import config, message, request
    from wechat_agent.context.chunks import plan_chunks

    original = message(1, body='历史订单🙂' * 500)
    reply = message(2, body='确认走货', reply='1')
    chunks = plan_chunks([original, reply], request, config(20_000), soft_input_target=2400)
    original_spans = [s for c in chunks for s in c.spans if s.message_id == '1']
    assert len(original_spans) > 1
    assert original_spans[0].start == 0 and original_spans[-1].end == len(original['body'])
    assert all(a.end == b.start for a, b in zip(original_spans, original_spans[1:]))
    reply_chunk = next(c for c in chunks if any(s.message_id == '2' for s in c.spans))
    assert original in reply_chunk.messages and reply_chunk.budget.fits


def test_short_reply_reference_does_not_allow_a_huge_primary_request():
    from tests.test_context_chunks import config, message, request
    from wechat_agent.context.chunks import plan_chunks

    original = message(1, body='请发订单资料')
    long_reply = message(2, body='历史订单🙂' * 500, reply='1')
    chunks = plan_chunks([original, long_reply], request, config(20_000), soft_input_target=2400)
    reply_chunks = [c for c in chunks if any(s.message_id == '2' for s in c.spans)]
    assert len(reply_chunks) > 1
    assert all(original in c.messages and c.budget.input_tokens <= 2400 for c in reply_chunks)
