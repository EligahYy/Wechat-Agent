"""Unit-local aliases and filtering of invalid references from extraction fields."""
from copy import deepcopy

from ..profiles.contracts import AnalysisResult, Fact
from .checkpoints import digest


def build_aliases(refs: set[tuple[str, int]]) -> dict[str, tuple[str, int]]:
    ordered = sorted(refs)
    namespace = digest(ordered)[:12]
    return {f'@{namespace}:{i}': ref for i, ref in enumerate(ordered, 1)}


def resolve_aliases(payload: dict, aliases: dict[str, tuple[str, int]]) -> dict:
    def visit(value):
        if isinstance(value, dict):
            alias = value.get('message_id')
            if isinstance(alias, str) and alias in aliases:
                identifier, revision = aliases[alias]
                if value.get('revision') == revision:
                    value['message_id'] = identifier
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    result = deepcopy(payload)
    visit(result)
    return result


def isolate_invalid_fields(result: AnalysisResult, allowed: set[tuple[str, int]]) -> AnalysisResult:
    def valid(refs):
        return all((ref.message_id, ref.revision) in allowed for ref in refs)

    result = result.model_copy(deep=True)
    gaps = set(result.gaps)
    for group in ('goods', 'logistics'):
        section = getattr(result, group)
        for name in type(section).model_fields:
            if not valid(getattr(section, name).sources):
                setattr(section, name, Fact())
                gaps.add(f'{group}.{name}:source_outside_unit')
    if not valid(result.communication.summary.sources):
        result.communication.summary = Fact()
        result.communication.tags = []
        result.communication.last_business_at = None
        gaps.add('communication.summary:source_outside_unit')
    batches = []
    for index, shipment in enumerate(result.shipments):
        path = f'shipments.{index}'
        if not valid(shipment.sources):
            gaps.add(f'{path}:source_outside_unit')
            continue
        for group in ('goods', 'logistics'):
            facts = getattr(shipment, group)
            if any(not valid(fact.sources) for fact in facts):
                gaps.add(f'{path}.{group}:source_outside_unit')
                setattr(shipment, group, [fact for fact in facts if valid(fact.sources)])
        batches.append(shipment)
    result.shipments = batches
    result.gaps = sorted(gaps)
    return result
