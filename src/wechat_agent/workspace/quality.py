"""Grounded output checks. Source chat text is never rewritten."""

import re
from decimal import Decimal

from .order_links import linked_keys

ENGINE_VERSION = "workspace-v10-complete-customer"
MODES = ("海运", "卡航", "班列")


def display_text(text):
    # Only internal actor aliases; never perform Chinese spelling substitutions.
    text = re.sub(r"(?<![A-Za-z])CUSTOMER(?![A-Za-z])", "该联系人", text)
    return re.sub(r"(?<![A-Za-z])SELF(?![A-Za-z])", "我方", text)


def validate_refs(keys, context):
    evidence = context["evidence"]
    if not keys or any(k not in evidence for k in keys):
        raise ValueError("workspace_unknown_evidence")
    if not any(evidence[k]["anchor"] for k in linked_keys(keys, evidence)):
        raise ValueError("workspace_customer_anchor_required")


def validate_proposal(proposal, context):
    evidence = context["evidence"]
    validate_refs(proposal.evidence, context)
    for item in [
        *proposal.notes,
        *proposal.batches,
        *proposal.actions,
        *proposal.decisions,
    ]:
        text = display_text(item.text)
        if hasattr(item, "reason"):
            item.reason = display_text(item.reason)
        item.text = text
        rendered = text + (getattr(item, "reason", "") or "")
        validate_refs(item.evidence, context)
        source = "\n".join(evidence[ref]["text"] for ref in item.evidence)
        if re.search(r"汽运|气运|空运", rendered):
            raise ValueError("workspace_transport_term")
        if any(mode in rendered and mode not in source for mode in MODES):
            raise ValueError("workspace_transport_evidence")
        # Prevent inventing quantities, postal/warehouse codes and quoted prices.
        linked_source = "\n".join(
            evidence[k]["text"] for k in linked_keys(item.evidence, evidence)
        )

        def numbers(value):
            return {
                Decimal(n)
                for n in re.findall(r"[0-9]+(?:\.[0-9]+)?", value.replace(",", ""))
            }

        if numbers(rendered) - numbers(linked_source):
            # Text-level numeric mismatch cannot invalidate an independently
            # evidenced shipment. Keep the claim visibly provisional.
            context.setdefault("field_warnings", {})[item.text] = [
                "numbers_need_review"
            ]
        if re.search(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", rendered):
            raise ValueError("workspace_internal_alias")
    return proposal


def isolate_invalid_items(proposal, context):
    """Last bounded attempt: retain grounded notes, withhold unsafe conclusions."""
    # Overall customer identity must be evidenced; never attach an arbitrary
    # customer message just to satisfy the validator.
    validate_refs(proposal.evidence, context)
    safe = proposal.model_copy(deep=True)
    issues = []
    for section in ("notes", "batches", "actions", "decisions"):
        kept = []
        for index, item in enumerate(getattr(safe, section)):
            probe = safe.model_copy(
                update={"notes": [], "batches": [], "actions": [], "decisions": []}
            )
            setattr(probe, section, [item])
            try:
                validate_proposal(probe, context)
            except ValueError as exc:
                if str(exc) not in {
                    "workspace_transport_term",
                    "workspace_transport_evidence",
                    "workspace_number_evidence",
                    "workspace_internal_alias",
                    "workspace_customer_anchor_required",
                }:
                    raise
                issues.append({"section": section, "index": index, "code": str(exc)})
                context.setdefault("unattributed", []).append(
                    {"section": section, "code": str(exc), "item": item.model_dump()}
                )
            else:
                kept.append(item)
        setattr(safe, section, kept)
    if issues:
        # Partial extraction cannot establish batch/action completeness or role.
        if any(i["section"] == "batches" for i in issues):
            removed = {
                v
                for entry in context.get("unattributed", [])
                if entry["section"] == "batches"
                for v in (entry["item"].get("ref"), entry["item"].get("origin"))
                if v
            }
            safe.actions = [a for a in safe.actions if a.batch not in removed]
        # A bad note does not invalidate independently grounded obligations.

        context["quality_issues"] = issues
        context["complete"] = False
    return validate_proposal(safe, context)
