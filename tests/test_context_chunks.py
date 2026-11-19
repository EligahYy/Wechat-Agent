import json
from datetime import datetime,timezone
import pytest
from wechat_agent.model.contracts import ModelCapabilities,ModelConfig,ModelRequest,ModelCallError

def config(window=4000):
    return ModelConfig(version='v',endpoint='https://example.test/chat/completions',model_id='synthetic',credential_ref='unused',capabilities=ModelCapabilities(model_id='synthetic',context_tokens=window,max_output_tokens=128,structured_output=True,vision=False,verified_at=datetime.now(timezone.utc)))

def request(messages):
    return ModelRequest(call_id='call',unit_id='unit',snapshot_id='snapshot',phase='extract',model_config_version='v',messages=[{'role':'system','content':'固定规则'},{'role':'user','content':json.dumps({'messages':messages},ensure_ascii=False)}],output_schema={'type':'object'},output_tokens=128)

def message(i,body='Unicode 汉字🙂 quoted " text\n'*10,room='room',reply=None):
    return dict(message_id=str(i),revision=1,conversation_id=room,sender_id='p',sent_at=f'2026-01-01T00:{i%60:02}:00+00:00',body=body,reply_to=reply)

def test_wire_budget_counts_actual_schema_and_reserves_output_and_repair():
    from wechat_agent.context.tokens import request_budget,wire_payload,estimate_tokens
    req=request([message(1)])
    cfg=config()
    b=request_budget(req,cfg)
    wire=json.dumps(wire_payload(req,cfg),ensure_ascii=False,separators=(',',':'))
    assert b.input_tokens==len(wire.encode())+256
    assert b.total_tokens==b.input_tokens+128+400
    assert b.method=='utf8-upper-bound-v1' and b.fits
    assert estimate_tokens('中文🙂','synthetic')==10
    exact=request_budget(req,cfg,counter=lambda text:7)
    assert exact.input_tokens==7+256 and exact.method=='provided-tokenizer'
    assert not request_budget(req,config(200)).fits

def test_chunks_preserve_all_revision_spans_and_required_reply():
    from wechat_agent.context.chunks import plan_chunks
    rows=[message(i,room='a' if i<8 else 'b',reply='0' if i==7 else None) for i in range(16)]
    chunks=plan_chunks(rows,request,config())
    assert len(chunks)>2
    seen=[]
    for c in chunks:
        assert c.budget.fits
        assert len({m['conversation_id'] for m in c.messages if m['message_id']!='0'})==1
        for span in c.spans:seen.append((span.message_id,span.revision,span.start,span.end))
        if any(s.message_id=='7' for s in c.spans):assert '0' in {m['message_id'] for m in c.messages}
    assert sorted(seen)==sorted((m['message_id'],1,0,len(m['body'])) for m in rows)
    assert [c.model_dump() for c in chunks]==[c.model_dump() for c in plan_chunks(rows,request,config())]

def test_very_long_message_is_split_without_truncation_or_broken_unicode():
    from wechat_agent.context.chunks import plan_chunks
    row=message(1,body='很长🙂中文内容'*4000)
    chunks=plan_chunks([row],request,config())
    assert len(chunks)>5
    spans=[s for c in chunks for s in c.spans]
    assert spans[0].start==0 and spans[-1].end==len(row['body'])
    assert all(a.end==b.start for a,b in zip(spans,spans[1:]))
    assert ''.join(c.messages[-1]['body'] for c in chunks)==row['body']

def test_fixed_overhead_and_required_reply_cannot_be_silently_dropped():
    from wechat_agent.context.chunks import plan_chunks
    with pytest.raises(ModelCallError,match='模型请求未完成') as e:plan_chunks([message(1)],request,config(200))
    assert e.value.code=='context_fixed_overhead_exceeded'
    with pytest.raises(ModelCallError) as e:plan_chunks([message(0,body='超长引用'*5000),message(1,reply='0')],request,config())
    assert e.value.code=='context_reference_too_large'


def test_material_target_does_not_spend_original_text_budget_on_fixed_rules():
    from wechat_agent.context.chunks import plan_chunks

    rows = [message(i, body='货物已到，核对报价与体积。' * 4) for i in range(278)]
    def with_rules(items):
        req = request(items)
        req.messages[0].content = '固定规则' * 1400
        return req

    cfg = config(1_000_000)
    legacy = plan_chunks(rows, with_rules, cfg, soft_input_target=8_000)
    planned = plan_chunks(rows, with_rules, cfg, soft_material_target=24_000)
    assert len(legacy) > 20
    assert len(planned) <= 6
    assert all(chunk.budget.fits for chunk in planned)
    assert [span.message_id for chunk in planned for span in chunk.spans] == [row['message_id'] for row in rows]
