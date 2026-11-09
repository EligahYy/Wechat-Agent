"""Read models for the unified customer workspace; no model requests."""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..analysis import budget_state
from ..config import secret
from ..db import dumps
from ..model_network import transport_summary
from .ocr import available
from .store import eligible, read, stable


def settings(db, background=False):
    account = db.settings.source_account
    rows = db.rows("SELECT * FROM crm_policies WHERE account_id=?", (account,))
    policy = (
        rows[0]
        if rows
        else {"enabled": False, "include_new": True, "daily_budget": 100000}
    )
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    usage = {
        r["day"]: r
        for r in db.rows(
            "SELECT day,SUM(COALESCE(actual,0)) reported,SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END) uncertain,COUNT(*) calls FROM usage WHERE day>=? GROUP BY day",
            ((today - timedelta(days=6)).isoformat(),),
        )
    }
    week = [
        usage.get(
            (today - timedelta(days=i)).isoformat(),
            {
                "day": (today - timedelta(days=i)).isoformat(),
                "reported": 0,
                "uncertain": 0,
                "calls": 0,
            },
        )
        for i in reversed(range(7))
    ]
    totals = db.rows(
        "SELECT COUNT(*) messages,SUM(m.type IN ('3','image')) images FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=?",
        (account,),
    )[0]
    return {
        "account_id": account,
        "account_name": db.settings.source_name,
        "policy": policy,
        "model": db.settings.model,
        "key_configured": bool(secret("DEEPSEEK_API_KEY")),
        "key_source": "environment" if os.environ.get("DEEPSEEK_API_KEY") else "system",
        "budget": budget_state(db),
        "week": week,
        "archive": totals,
        "background": bool(background),
        "mode": db.settings.analysis_mode,
        "transport": transport_summary(),
        "ocr": available(),
    }


def journal(db, source_id, page=1):
    eligible(db, source_id)
    if page < 1 or page > 100000:
        raise ValueError("workspace_invalid_query")
    ident = stable(db.settings.source_account, source_id)
    rows = db.rows(
        "SELECT payload,created_at FROM events WHERE entity_id=? AND kind='workspace_followup' ORDER BY rowid DESC LIMIT 20 OFFSET ?",
        (ident, (page - 1) * 20),
    )
    return {
        "items": [
            json.loads(r["payload"]) | {"created_at": r["created_at"]} for r in rows
        ],
        "page": page,
        "has_more": len(rows) == 20,
    }


def history(db, source_id):
    document = read(db, source_id)
    if not document:
        raise ValueError("workspace_not_found")
    return db.rows(
        "SELECT version,reason,created_at FROM workspace_versions WHERE document_id=? ORDER BY version DESC LIMIT 30",
        (document["id"],),
    )


def enrich_images(db, messages):
    if not messages:
        return messages
    ids = [m["id"] for m in messages]
    found = {
        r["message_id"]: r
        for r in db.rows(
            "SELECT x.message_id,x.version,x.confirmed_text FROM message_extractions x JOIN messages m ON m.id=x.message_id AND m.revision=x.source_revision JOIN attachments a ON a.message_id=x.message_id AND a.sha256=x.sha256 WHERE x.message_id IN (SELECT value FROM json_each(?))",
            (dumps(ids),),
        )
    }
    return [m | {"image_text": found.get(m["id"])} for m in messages]
