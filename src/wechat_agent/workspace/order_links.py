"""Exact order references connect a customer's request to logistics replies."""

import re


def orders(text):
    # Conservative: explicit mixed letter/digit codes, not names or dates.
    return set(
        re.findall(
            r"(?<![A-Za-z0-9])(?:[A-Z]{2,8}\d{4,}(?:-\d+)*)(?![A-Za-z0-9])", text
        )
    )


def link_index(evidence):
    index = {}
    for ref, m in evidence.items():
        if m["anchor"]:
            for code in orders(m["text"]):
                index.setdefault((m["conversation_id"], code), set()).add(ref)
    return index


def linked_keys(keys, evidence, index=None):
    index = link_index(evidence) if index is None else index
    result = set(keys)
    for key in keys:
        message = evidence.get(key)
        if message:
            for code in orders(message["text"]):
                result.update(index.get((message["conversation_id"], code), ()))
    return sorted(result)
