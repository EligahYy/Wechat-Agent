"""Exact order references connect a customer's request to logistics replies."""

import re


def orders(text):
    # Conservative: explicit mixed letter/digit codes, not names or dates.
    return set(
        re.findall(
            r"(?<![A-Za-z0-9])(?:[A-Z]{2,8}\d{4,}(?:-\d+)*)(?![A-Za-z0-9])", text
        )
    )


def linked_keys(keys, evidence):
    result = set(keys)
    for key in keys:
        message = evidence.get(key)
        if not message:
            continue
        codes = orders(message["text"])
        if not codes:
            continue
        for ref, anchor in evidence.items():
            if (
                anchor["anchor"]
                and anchor["conversation_id"] == message["conversation_id"]
                and codes & orders(anchor["text"])
            ):
                result.add(ref)
    return sorted(result)
