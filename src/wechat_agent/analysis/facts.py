"""Validate per-unit evidence and retain sparse, deduplicated typed facts."""
from ..profiles.contracts import AnalysisResult
from ..profiles.validator import validate_result
from ..model.contracts import ModelCallError
from .checkpoints import canonical


def source_refs(result):
    for group in (result.goods,result.logistics):
        for name in type(group).model_fields:yield from getattr(group,name).sources
    yield from result.communication.summary.sources
    for shipment in result.shipments:
        yield from shipment.sources
        for fact in [*shipment.goods,*shipment.logistics]:yield from fact.sources


def validate_unit(conn,snapshot,payload,allowed):
    try:result=AnalysisResult.model_validate(payload)
    except ValueError:raise ModelCallError('output_invalid') from None
    if result.contact_id!=snapshot.key.contact_id:raise ModelCallError('target_mismatch')
    if any((r.message_id,r.revision) not in allowed for r in source_refs(result)):
        raise ModelCallError('chunk_source_outside_unit')
    checked=validate_result(conn,snapshot,result)
    if checked.reason and checked.reason!='empty_result':raise ModelCallError(checked.reason)
    clean=checked.result or AnalysisResult(contact_id=snapshot.key.contact_id)
    clean.gaps=sorted(set(result.gaps)|set(checked.issues))
    return clean


def sparse(result):return result.model_dump(mode='json',exclude_defaults=True,exclude_none=True)


def deduplicate(results):
    return [candidate for _,candidates in merge_groups(results,results[0].contact_id) for candidate in candidates]


def merge_groups(results,contact_id):
    """No recursive summaries: each field/batch receives all its extracted facts."""
    groups=[]
    for group in ('goods','logistics'):
        for name in type(getattr(results[0],group)).model_fields:
            candidates=[]
            for result in results:
                fact=getattr(getattr(result,group),name)
                if fact.state!='not_mentioned':
                    candidates.append({ 'contact_id':contact_id,group:{name:fact.model_dump(mode='json',exclude_none=True)}})
            if candidates:
                coalesced={}
                for candidate in candidates:
                    fact=candidate[group][name]
                    semantic=canonical({k:v for k,v in fact.items() if k!='sources'})
                    if semantic not in coalesced:coalesced[semantic]=candidate
                    else:
                        sources=[*coalesced[semantic][group][name]['sources'],*fact['sources']]
                        coalesced[semantic][group][name]['sources']=list({canonical(r):r for r in sources}.values())
                groups.append((f'{group}.{name}',list(coalesced.values())))
    communication=[{'contact_id':contact_id,'communication':r.communication.model_dump(mode='json',exclude_defaults=True,exclude_none=True)} for r in results if r.communication.summary.state!='not_mentioned']
    if communication:groups.append(('communication',list({canonical(c):c for c in communication}.values())))
    batches={}
    for result in results:
        for shipment in result.shipments:
            key=shipment.existing_id or shipment.candidate_key
            batches.setdefault(key,[]).append({'contact_id':contact_id,'shipments':[shipment.model_dump(mode='json',exclude_none=True)]})
    for key,candidates in sorted(batches.items()):groups.append(('shipments',list({canonical(c):c for c in candidates}.values())))
    return groups


def combine(results,contact_id):
    combined=AnalysisResult(contact_id=contact_id)
    for label,result in results:
        if label=='all':return result
        if label=='communication':combined.communication=result.communication
        elif label=='shipments':combined.shipments.extend(result.shipments)
        else:
            group,name=label.split('.')
            setattr(getattr(combined,group),name,getattr(getattr(result,group),name))
        combined.gaps=sorted(set(combined.gaps)|set(result.gaps))
    return combined


def enforce_merge_scope(result,label,candidates):
    if label=='all':return
    allowed={}
    if label=='communication':allowed={'communication':result.communication.model_dump()}
    elif label=='shipments':
        allowed={'shipments':[b.model_dump() for b in result.shipments]}
        candidate_ids={b.get('existing_id') or b['candidate_key'] for c in candidates for b in c.get('shipments',[])}
        if any((b.existing_id or b.candidate_key) not in candidate_ids for b in result.shipments):raise ModelCallError('merge_scope_invalid')
    else:
        group,name=label.split('.');allowed={group:{name:getattr(getattr(result,group),name).model_dump()}}
    projected=AnalysisResult(contact_id=result.contact_id,**allowed,gaps=result.gaps)
    if projected!=result:raise ModelCallError('merge_scope_invalid')
