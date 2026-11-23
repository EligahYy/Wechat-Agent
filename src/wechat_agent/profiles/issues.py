"""Display policy for persisted issue strings, including legacy records."""
from collections import Counter
from dataclasses import dataclass
from typing import Literal

IssueSeverity = Literal['blocker', 'field_warning', 'coverage_notice', 'business_uncertainty']


@dataclass(frozen=True)
class ProfileIssue:
    code: str
    severity: IssueSeverity
    field_path: str | None = None
    count: int = 1
    detail: str | None = None


def classify_issues(legacy: list[str]) -> list[ProfileIssue]:
    counts: Counter[tuple[str, IssueSeverity, str | None, str | None]] = Counter()
    for entry in sorted(set(legacy)):
        path, _, reason = entry.partition(':')
        if path == 'communication.tags' and reason == 'summary_missing' and any(
            item.startswith('communication.summary:') for item in legacy
        ):
            continue
        if path in {'attachment_not_processed', 'history_complete_unverified', 'reply_unavailable'}:
            counts[(path, 'coverage_notice', None, None)] += 1
        elif path in {'source_not_complete', 'source_issue', 'source_gap', 'source_message_id_unavailable'}:
            counts[(path, 'coverage_notice', None, reason or None)] += 1
        elif path == 'prior_shipment_needs_review':
            counts[(path, 'field_warning', None, None)] += 1
        elif path.startswith(('goods.', 'logistics.', 'communication.', 'shipments.')):
            counts[(reason or 'evidence_invalid', 'field_warning', path, None)] += 1
        elif entry.startswith(('事实尚未明确：', '事实尚未明确:', '未确认：', '未确认:')):
            counts[('business_uncertainty', 'business_uncertainty', None, entry)] += 1
        else:
            counts[('analysis_review_required', 'field_warning', None, entry)] += 1
    return [ProfileIssue(code, severity, path, count, detail)
            for (code, severity, path, detail), count in counts.items()]
