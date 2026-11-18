"""Sparse provider extraction envelope with optional explicit coverage evidence."""
from pydantic import Field

from ..model.contracts import ModelCallError
from ..profiles.contracts import AnalysisResult


class ExtractedFacts(AnalysisResult):
    # Defaults in AnalysisResult allow empty sections to be omitted. Older
    # providers may omit the acknowledgement; span proof stays application-owned.
    processed_primary_ids: list[str] | None = Field(default=None, max_length=5000)


def normalize_extraction(payload, primary_ids, aliases):
    acknowledgement = payload.get('processed_primary_ids')
    if acknowledgement is not None:
        actual = [aliases.get(identifier, (identifier, 0))[0] for identifier in acknowledgement]
        if len(actual) != len(set(actual)) or set(actual) != primary_ids:
            raise ModelCallError('history_coverage_incomplete')
    return {key: value for key, value in payload.items() if key != 'processed_primary_ids'}
