"""Bounded reduction with a durable ledger of the candidates each node covers."""
from ..model.contracts import ModelCallError
from ..profiles.contracts import AnalysisResult, Fact
from ..source.repository import transaction, cancellation_requested
from .checkpoints import canonical, digest
from .facts import source_refs


def references(candidate):
    return {(ref.message_id, ref.revision) for ref in source_refs(candidate)}


def preserves_candidate(result, candidate):
    def refs(items):
        return {canonical(ref.model_dump(mode='json')) for ref in items}

    def contains_value(output, source):
        if not refs(source.sources) <= refs(output.sources):
            return False
        if source.event_time is not None and source.event_time != output.event_time:
            return False
        if source.batch_ref is not None and source.batch_ref != output.batch_ref:
            return False
        if not source.value:
            return True
        return bool(output.value and f'；{source.value}；' in f'；{output.value}；')

    for group in ('goods', 'logistics'):
        original = getattr(candidate, group)
        final = getattr(result, group)
        if any(not contains_value(getattr(final, name), getattr(original, name))
               for name in type(original).model_fields):
            return False
    if not contains_value(result.communication.summary, candidate.communication.summary):
        return False
    for original in candidate.shipments:
        identity = original.existing_id or original.candidate_key
        matches = [
            batch for batch in result.shipments
            if identity in {batch.existing_id, batch.candidate_key}
            and batch.stage == original.stage and set(original.numbers) <= set(batch.numbers)
            and refs(original.sources) <= refs(batch.sources)
        ]
        if not any(all(
            any(contains_value(output, source) for output in getattr(batch, group))
            for group in ('goods', 'logistics') for source in getattr(original, group)
        ) for batch in matches):
            return False
    return True


def communication_status(items):
    dated = [item for item in items if item.last_business_at is not None]
    stamp = max((item.last_business_at for item in dated), default=None)
    tagged = [item for item in items if item.tags]
    latest = max((item.last_business_at for item in tagged if item.last_business_at), default=None)
    statuses = {tuple(sorted(item.tags)) for item in tagged if item.last_business_at == latest}
    return list(next(iter(statuses))) if len(statuses) == 1 else [], stamp, len(statuses) > 1


def record_reduction(conn, snapshot, token, label, candidates, result):
    input_ids = sorted({digest(candidate) for candidate in candidates})
    parsed = [AnalysisResult.model_validate(candidate) for candidate in candidates]
    expected = set().union(*(references(candidate) for candidate in parsed))
    dispositions = {
        digest(value): 'retained'
        for value, candidate in zip(candidates, parsed)
        if preserves_candidate(result, candidate)
    }
    communications = [candidate.communication for candidate in parsed
                      if candidate.communication.summary.value]
    if communications:
        tags, stamp, conflict = communication_status(communications)
        if (sorted(result.communication.tags) != tags
                or result.communication.last_business_at != stamp
                or (conflict and 'communication.status_conflict' not in result.gaps)):
            raise ModelCallError('history_merge_incomplete')
    if not expected or references(result) != expected or set(dispositions) != set(input_ids):
        raise ModelCallError('history_merge_incomplete')
    with transaction(conn):
        if cancellation_requested(conn, snapshot.key.account_id, token):
            raise ModelCallError('model_cancelled')
        conn.execute(
            '''INSERT INTO history_reduction_nodes VALUES(?,?,?,?,?,?,?)
               ON CONFLICT DO NOTHING''',
            (snapshot.key.account_id, snapshot.id, digest([label, input_ids]),
             canonical(input_ids), canonical(dispositions), canonical(candidates), result.model_dump_json()),
        )


def shared_metadata(facts):
    values = {}
    for key in ('event_time', 'batch_ref'):
        known = {getattr(fact, key) for fact in facts if getattr(fact, key) is not None}
        if len(known) > 1:
            raise ModelCallError('history_merge_incomplete')
        values[key] = next(iter(known), None)
    return values


def combine_field(label, candidates, contact_id):
    """Preserve competing values and all verified references for field conflicts."""
    if len(candidates) == 1 and label != 'shipments':
        return AnalysisResult.model_validate(candidates[0])
    if label == 'communication':
        values = [AnalysisResult.model_validate(candidate).communication for candidate in candidates]
        summaries = list(dict.fromkeys(item.summary.value for item in values if item.summary.value))
        refs = {(ref.message_id, ref.revision): ref for item in values for ref in item.summary.sources}
        if not summaries or not refs:
            return None
        body = '；'.join(summaries)
        if len(body) > 16_000:
            raise ModelCallError('history_merge_unit_too_large')
        tags, stamp, conflict = communication_status(values)
        return AnalysisResult(
            contact_id=contact_id,
            communication={
                'summary': Fact(value=body, state='uncertain', sources=list(refs.values()),
                                **shared_metadata([item.summary for item in values])),
                'tags': tags, 'last_business_at': stamp,
            },
            gaps=['communication.status_conflict'] if conflict else [],
        )
    if not label.startswith(('goods.', 'logistics.')):
        return None
    group, field = label.split('.', 1)
    facts = [Fact.model_validate(candidate[group][field]) for candidate in candidates]
    values = list(dict.fromkeys(fact.value for fact in facts if fact.value))
    refs = {(ref.message_id, ref.revision, ref.attachment_id, ref.locator): ref
            for fact in facts for ref in fact.sources}
    if not values or not refs:
        return None
    value = '；'.join(values)
    gaps = []
    if len(value) > 16_000:
        raise ModelCallError('history_merge_unit_too_large')
    if len(values) > 1:
        gaps.append(f'{label}:conflicting_candidates')
    state = 'known' if len(values) == 1 and all(f.state == 'known' for f in facts) else 'uncertain'
    fact = Fact(value=value, state=state, sources=list(refs.values()), **shared_metadata(facts))
    return AnalysisResult(contact_id=contact_id, **{group: {field: fact}}, gaps=gaps)
