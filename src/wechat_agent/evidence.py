"""Allowlisted technical diagnostics for feedback, separate from private reports."""

import re


_SAFE_FACTS = {
    "python", "platform", "architecture", "scope", "ready", "cli_version", "account_fingerprint",
    "account_pinned", "history_complete", "contacts_checked", "groups_checked", "message_pages_checked",
    "messages_checked", "messages_valid", "messages_sampled", "messages_rejected", "sample_has_more",
    "system_events_checked", "unattributed_events_checked",
    "live_connection_verified", "files_checked", "parsed",
    "requested_model_id", "reported_model_id", "response_mode", "declared_context_tokens", "capacity_verified",
    "vision", "json_output_verified", "json_mode_accepted", "schema_mode_accepted", "usage_unknown",
}
_SAFE_FILE = {"index", "state", "quality", "parsed", "size_bytes", "sha256", "mime", "type_detection", "gap"}
_ISSUE_ENUMS = {
    "reason": ("message_sender_missing", "source_message_id_unavailable", "message_contract_invalid"),
    "conversation_kind": ("private", "group"),
    "direction": ("incoming", "outgoing", "unknown"),
}


def _technical(value):
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, str) and len(value) <= 256:
        if value.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value) or "\n" in value:
            return "[redacted]"
        return value
    return None


def sanitize_evidence(report: dict) -> dict:
    result = {"schema_version": report.get("schema_version", 1), "checked_at": report.get("checked_at")}
    for name in ("runtime", "source", "model", "media"):
        component = report.get(name, {})
        facts = component.get("facts", {})
        safe = {key: _technical(value) for key, value in facts.items() if key in _SAFE_FACTS}
        usage = facts.get("usage")
        if isinstance(usage, dict):
            safe["usage"] = {key: value for key, value in usage.items()
                             if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(value) is int and value >= 0}
        elif "usage" in facts:
            safe["usage"] = None
        if isinstance(facts.get("files"), list):
            safe["files"] = [{key: _technical(value) for key, value in item.items() if key in _SAFE_FILE}
                             for item in facts["files"] if isinstance(item, dict)]
        if isinstance(facts.get("schema_errors"), list):
            safe["schema_errors"] = [{key: _technical(item[key]) for key in ("path", "type") if key in item}
                                     for item in facts["schema_errors"] if isinstance(item, dict)]
        if isinstance(facts.get("message_issues"), list):
            safe["message_issues"] = []
            for item in facts["message_issues"]:
                if not isinstance(item, dict):
                    continue
                issue = {key: item[key] for key, values in _ISSUE_ENUMS.items() if item.get(key) in values}
                for key in ("item_index", "page_offset", "msg_type", "sub_type"):
                    value = item.get(key)
                    if type(value) is int and 0 <= value <= 0xFFFFFFFF:
                        issue[key] = value
                    elif key in {"msg_type", "sub_type"}:
                        issue[key] = None
                safe["message_issues"].append(issue)
        result[name] = {
            "component": name, "status": component.get("status", "pending"), "facts": safe,
            "gaps": [gap for gap in component.get("gaps", [])
                     if isinstance(gap, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", gap)],
        }
    return result
