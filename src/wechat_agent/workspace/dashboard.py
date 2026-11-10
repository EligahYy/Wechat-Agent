"""One read-only screen: contacts, valid dossiers, follow-ups and live jobs."""

from ..identity import location
from .queue import _jobs
from .store import source_chats
from .views import listing

FILTERS = {"all", "customers", "tasks", "review", "running", "unanalyzed"}
FOLLOWUPS = {"all", "today", "upcoming", "waiting"}


def snapshot(
    db, q="", selected="all", page=1, followup="all", followup_page=1, background=True
):
    if (
        len(q) > 200
        or selected not in FILTERS
        or followup not in FOLLOWUPS
        or not 1 <= page <= 100000
        or not 1 <= followup_page <= 100000
    ):
        raise ValueError("workspace_invalid_query")
    jobs, automation = _jobs(db, background, include_sources=True)
    documents = {
        d["source_id"]: d
        for d in listing(db, compact=True, include_non_target=True)["items"]
    }
    scoped = {v["id"]: v for v in source_chats(db)}
    rows, lane = [], []
    for job in jobs:
        source = job["source_id"]
        document = documents.get(source)
        body = document["body"] if document else {}
        groups = (
            document["task_groups"]
            if document
            else {"upcoming": [], "waiting": [], "done": []}
        )
        today = document["today_action_ids"] if document else []
        actionable = today + groups["upcoming"] + groups["waiting"]
        proposed = [
            k for k, a in body.get("actions", {}).items() if a["state"] == "proposed"
        ]
        decisions = sum(
            not d.get("resolved") for d in body.get("decisions", {}).values()
        )
        review = decisions + len(proposed) + len(body.get("unattributed", []))
        notes = body.get("notes", {})
        summary = next(iter(notes.values()), {}).get("text", "")
        if not summary:
            summary = next(iter(body.get("batches", {}).values()), {}).get("text", "")
        loc = document["location"] if document else location(db, source)
        origins = [c for c in loc["conversations"] if c["id"] in scoped]
        row = job | {
            "document_id": document["id"] if document else None,
            "relationship": body.get("relationship", "unclassified"),
            "summary": summary,
            "task_count": len(actionable),
            "review_count": review,
            "review_tab": "overview" if body.get("unattributed") else "work",
            "today_count": len(today),
            "paused_contact": bool(body.get("paused")),
            "needs_update": bool(document and document["needs_update"]),
            "origins": origins,
            "next_task": {
                k: body["actions"][actionable[0]].get(k)
                for k in ("text", "due_date", "state")
            }
            if actionable
            else None,
        }
        # Invalidated dossiers never leak their previous facts into this screen.
        if row["status"] == "succeeded" and (not document or document["needs_update"]):
            row.update(
                status="ready",
                status_label="等待更新",
                phase="update",
                phase_label="新进展待整理" if document else "档案待核对",
                stage_detail="有新记录或人工判断，可复用已有分册更新"
                if document
                else "来源已变化，重新整理后查看档案",
                stage_completed=0,
                stage_total=0,
                primary_action={
                    "action": "start",
                    "label": "更新分析",
                    "disabled": bool(
                        job["action_hint"]
                        or automation["gate"]
                        in {
                            "blocked_policy",
                            "blocked_credentials",
                            "awaiting_account",
                            "legacy_mode",
                        }
                    ),
                },
            )
        rows.append(row)
        ids = (
            actionable
            if followup == "all"
            else today
            if followup == "today"
            else groups[followup]
        )
        if ids:
            first = body["actions"][ids[0]]
            lane.append(
                row
                | {
                    "source_id": source,
                    "name": job["name"],
                    "document_id": document["id"],
                    "text": first["text"],
                    "reason": first.get("reason", ""),
                    "due_date": first.get("due_date"),
                    "waiting": first["state"] == "waiting",
                    "task_count": len(ids),
                    "next_task": {
                        k: first.get(k) for k in ("text", "due_date", "state")
                    },
                    "today": bool(today),
                }
            )
    counts = {
        "contacts": len(rows),
        "customers": sum(r["relationship"] == "merchant" for r in rows),
        "tasks": sum(r["task_count"] > 0 for r in rows),
        "task_items": sum(r["task_count"] for r in rows),
        "review": sum(r["review_count"] > 0 for r in rows),
        "running": sum(
            r["status"] in {"running", "starting", "stopping"} for r in rows
        ),
        "unanalyzed": sum(not r["document_id"] for r in rows),
    }
    query = q.casefold().strip()
    rows = [
        r
        for r in rows
        if query
        in " ".join(
            [r["name"], r["source_id"], *(c["title"] for c in r["origins"])]
        ).casefold()
        and (
            selected == "all"
            or selected == "customers"
            and r["relationship"] == "merchant"
            or selected == "tasks"
            and r["task_count"] > 0
            or selected == "review"
            and r["review_count"] > 0
            or selected == "running"
            and r["status"] in {"running", "starting", "stopping"}
            or selected == "unanalyzed"
            and not r["document_id"]
        )
    ]
    rows.sort(
        key=lambda r: (
            r["status"] in {"running", "starting", "stopping"},
            r["latest_event"],
            r["source_id"],
        ),
        reverse=True,
    )
    matched_total = len(rows)
    matched = {r["source_id"] for r in rows}
    lane = [r for r in lane if r["source_id"] in matched]
    lane.sort(
        key=lambda r: (not r["today"], r["waiting"], r["due_date"] or "", r["name"])
    )
    rows = [r for r in rows if r["task_count"] == 0]
    total, lane_total = len(rows), len(lane)
    pages, lane_pages = max(1, (total + 19) // 20), max(1, (lane_total + 19) // 20)
    page, followup_page = min(page, pages), min(followup_page, lane_pages)
    return {
        "items": rows[(page - 1) * 20 : page * 20],
        "matched_total": matched_total,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": 20,
        "counts": counts,
        "automation": automation,
        "followups": {
            "items": lane[(followup_page - 1) * 20 : followup_page * 20],
            "total": lane_total,
            "page": followup_page,
            "pages": lane_pages,
            "page_size": 20,
        },
    }
