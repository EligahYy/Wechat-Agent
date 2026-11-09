"""Human review of retained model inferences, without changing raw evidence."""

from ..db import dumps, now
from .quality import display_text
from .schema import ClueResolution


def key(item):
    from .store import stable

    return stable(
        "clue",
        item["section"],
        display_text(item["text"]),
        sorted(item.get("evidence", []), key=dumps),
    )


def pending(body):
    resolved = body.get("clue_resolutions", {})
    return list(
        {
            key(item): item | {"id": key(item)}
            for item in body.get("unattributed", [])
            if key(item) not in resolved
        }.values()
    )


def sync_issues(body):
    body["quality_issues"] = [
        {"section": item["section"], "code": item["code"]}
        for item in body["unattributed"]
    ]


def resolve(db, body, target, value):
    from .store import stable, valid_refs

    result = ClueResolution.model_validate(value)
    items = pending(body)
    item = next((x for x in items if x["id"] == target), None)
    if item is None:
        raise ValueError("workspace_clue_not_pending")
    note_id = None
    text = display_text(result.text.strip())
    if result.choice == "confirmed":
        if result.belongs_to_customer is not True or not text:
            raise ValueError("workspace_clue_verification_required")
        if not valid_refs(db, item["evidence"]):
            raise ValueError("workspace_stale_evidence")
        # This is a human attribution, not a fabricated customer message anchor.
        # Reviewing a quarantined batch/action never directly opens a task.
        note_id = stable("verified-clue", target)
        body["notes"][note_id] = {
            "text": text,
            "evidence": item["evidence"],
            "text_locked": True,
            "manual_verified": True,
            "source_clue": target,
        }
    body.setdefault("clue_resolutions", {})[target] = {
        "choice": result.choice,
        "text": text if result.choice == "confirmed" else item["text"],
        "original": item,
        "note_id": note_id,
        "at": now(),
    }
    body["unattributed"] = [x for x in items if x["id"] != target]
    sync_issues(body)
    body["source_revision"] = None


def restore(db, body, target):
    from .store import valid_refs

    resolution = body.get("clue_resolutions", {}).get(target)
    if not resolution:
        raise ValueError("workspace_clue_not_resolved")
    item = resolution["original"]
    if not valid_refs(db, item["evidence"]):
        raise ValueError("workspace_stale_evidence")
    note = body["notes"].get(resolution["note_id"])
    if note and note.get("source_clue") == target:
        del body["notes"][resolution["note_id"]]
    del body["clue_resolutions"][target]
    body["unattributed"] = pending(body) + [item | {"id": target}]
    sync_issues(body)
    body["source_revision"] = None
