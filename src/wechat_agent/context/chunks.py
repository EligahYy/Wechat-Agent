"""Pure, deterministic conversation partitions; never truncate a source body."""
from collections import defaultdict
from dataclasses import asdict,dataclass
from .tokens import request_budget,RequestBudget
from ..model.contracts import ModelCallError

@dataclass(frozen=True)
class MessageSpan:
    message_id:str
    revision:int
    start:int
    end:int
    total:int

@dataclass(frozen=True)
class ContextChunk:
    ordinal:int
    messages:tuple[dict,...]
    spans:tuple[MessageSpan,...]
    budget:RequestBudget

    def model_dump(self):return asdict(self)


def plan_chunks(messages,request_factory,config,*,input_limit=None,context_messages=None,max_primary_messages=None):
    originals={m['message_id']:m for m in (context_messages or messages)}
    groups=defaultdict(list)
    def budget(rows):return request_budget(request_factory(list(rows)),config)
    def fits(rows):
        value=budget(rows)
        return value.fits and (input_limit is None or value.input_tokens<=input_limit)
    if not fits([]):raise ModelCallError('context_fixed_overhead_exceeded')
    def identity(row):
        span=row.get('body_fragment',{})
        return row['message_id'],row['revision'],span.get('start',0),span.get('end',len(row['body']))
    def include(primary,previous=()):
        ids={m['message_id'] for m in primary}
        required={m['reply_to'] for m in primary if m.get('reply_to') and m['reply_to'] not in ids and m['reply_to'] in originals}
        context=[originals[key] for key in sorted(required)]
        if not fits([*context,*primary]):return None
        for row in reversed(previous[-2:]):
            if identity(row) in {identity(m) for m in [*context,*primary]}:continue
            if fits([row,*context,*primary]):context.insert(0,row)
        return [*context,*primary]
    # Split a large single message using Unicode character offsets. Every primary
    # span is later covered exactly once; copies of neighbours/replies are context.
    for row in messages:
        if include([row]) is not None:
            groups[row['conversation_id']].append(row);continue
        text=row['body'];offset=0
        if not text:raise ModelCallError('context_message_overhead_exceeded')
        while offset<len(text):
            part=row.get('body_fragment',{});origin=part.get('start',0)
            def fragment(end):return {**row,'body':text[offset:end],'body_fragment':{'start':origin+offset,'end':origin+end,'total':part.get('total',len(text))}}
            low,high=offset+1,len(text)
            if include([fragment(low)]) is None:
                raise ModelCallError('context_reference_too_large' if row.get('reply_to') in originals else 'context_message_overhead_exceeded')
            while low<high:
                mid=(low+high+1)//2
                if include([fragment(mid)]) is not None:low=mid
                else:high=mid-1
            groups[row['conversation_id']].append(fragment(low));offset=low
    chunks=[]
    for room in sorted(groups):
        rows=groups[room];start=0
        while start<len(rows):
            previous=rows[max(0,start-2):start]
            # Exponential search avoids reserializing the entire remaining history
            # for every chunk, then binary search finds a bounded prefix.
            good=1;bad=None
            while start+good<len(rows) and (max_primary_messages is None or good<max_primary_messages):
                candidate=min(len(rows)-start,good*2,max_primary_messages or len(rows))
                if include(rows[start:start+candidate],previous) is None:bad=candidate;break
                good=candidate
            if bad is not None:
                low,high=good,bad-1
                while low<high:
                    mid=(low+high+1)//2
                    if include(rows[start:start+mid],previous) is not None:low=mid
                    else:high=mid-1
                good=low
            primary=rows[start:start+good];visible=include(primary,previous)
            if visible is None:raise ModelCallError('context_reference_too_large')
            spans=[]
            for row in primary:
                part=row.get('body_fragment',{})
                spans.append(MessageSpan(row['message_id'],row['revision'],part.get('start',0),part.get('end',len(row['body'])),part.get('total',len(row['body']))))
            chunks.append(ContextChunk(len(chunks),tuple(visible),tuple(spans),budget(visible)))
            start+=good
    return chunks
