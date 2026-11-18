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


def plan_chunks(messages,request_factory,config,*,input_limit=None,context_messages=None,max_primary_messages=None,soft_input_target=None):
    originals={m['message_id']:m for m in (context_messages or messages)}
    groups=defaultdict(list)
    def budget(rows):return request_budget(request_factory(list(rows)),config)
    def fits(rows):
        value=budget(rows)
        return value.fits and (input_limit is None or value.input_tokens<=input_limit)
    if not fits([]):raise ModelCallError('context_fixed_overhead_exceeded')
    # Schema and mandatory metadata can themselves exceed the soft target.
    target = None if soft_input_target is None else max(soft_input_target, budget([]).input_tokens + 1024)
    def fits_target(rows, limit=target):
        value = budget(rows)
        return value.fits and (input_limit is None or value.input_tokens <= input_limit) and (
            limit is None or value.input_tokens <= limit
        )
    def include(primary,previous=()):
        ids = {row['message_id'] for row in primary}
        complete = {
            row['message_id'] for row in primary
            if not row.get('body_fragment')
            or (row['body_fragment']['start'] == 0 and row['body_fragment']['end'] == row['body_fragment']['total'])
        }
        required = ({row.get('reply_to') for row in primary} & originals.keys()) - complete
        # A fragment cannot stand in for the full original of a reply. Keep
        # the reply in a separate chunk so its context has one unambiguous row.
        if required & ids:
            return None
        context=[originals[key] for key in sorted(required)]
        required_rows = [*context, *primary]
        if not fits_target(required_rows):
            if len(primary) != 1:
                return None
            # Make headroom for mandatory context, not the whole primary body.
            # A long primary still gets split when its reply target is short.
            if target is not None:
                minimum = budget([*context, {**primary[0], 'body': ''}]).input_tokens
                limit = max(target, minimum + 1024)
                if len(primary[0]['body']) > 1 and not fits_target(required_rows, limit):
                    return None
            if not fits(required_rows):
                return None
        for row in reversed(previous[-2:]):
            if row['message_id'] in {m['message_id'] for m in [*context, *primary]}:continue
            if fits_target([row,*context,*primary]):context.insert(0,row)
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
