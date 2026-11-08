"""Grounded output checks. Source chat text is never rewritten."""

import re

ENGINE_VERSION = "workspace-v2-reviewed-tasks"
MODES = ("海运", "卡航", "班列")


def display_text(text):
    # Only internal actor aliases; never perform Chinese spelling substitutions.
    text = re.sub(r"(?<![A-Za-z])CUSTOMER(?![A-Za-z])", "该联系人", text)
    return re.sub(r"(?<![A-Za-z])SELF(?![A-Za-z])", "我方", text)


def validate_proposal(proposal, context):
    evidence = context["evidence"]
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
        if not item.evidence or any(ref not in evidence for ref in item.evidence):
            raise ValueError("workspace_unknown_evidence")
        source = "\n".join(evidence[ref]["text"] for ref in item.evidence)
        if re.search(r"汽运|气运|空运", rendered):
            raise ValueError("workspace_transport_term")
        if any(mode in rendered and mode not in source for mode in MODES):
            raise ValueError("workspace_transport_evidence")
        # Prevent inventing quantities, postal/warehouse codes and quoted prices.
        numbers = re.findall(r"[0-9]+(?:\.[0-9]+)?", rendered.replace(",", ""))
        if any(
            n not in re.findall(r"[0-9]+(?:\.[0-9]+)?", source.replace(",", ""))
            for n in numbers
        ):
            raise ValueError("workspace_number_evidence")
        if re.search(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", rendered):
            raise ValueError("workspace_internal_alias")
    return proposal
