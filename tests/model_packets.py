"""Deterministic packet fixture, separate from mocked CRM synthesis."""

import json

import httpx


def packet_response(request):
    payload = json.loads(json.loads(request.content)["messages"][1]["content"])
    if payload.get("phase") not in {"extract", "merge"}:
        return None
    facts = payload.get("facts") or [
        {
            "kind": "context",
            "text": m["text"][:500],
            "subject": "customer" if m["actor"] == "CUSTOMER" else "unclear",
            "evidence": [m["ref"]],
        }
        for m in payload.get("messages", [])
    ]
    if payload["phase"] == "merge":
        facts = facts[:8]
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({"facts": facts}, ensure_ascii=False)
                    },
                }
            ],
            "usage": {"total_tokens": 1},
        },
    )
