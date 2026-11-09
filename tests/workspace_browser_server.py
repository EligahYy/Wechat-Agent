"""Local-only new workspace browser fixture, with synthetic data and model."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from model_packets import packet_response

from wechat_agent.config import Settings
from wechat_agent.crm import configure
from wechat_agent.ingestion import ingest
from wechat_agent.services import allow_conversation
from wechat_agent.web import create_app
from wechat_agent.workspace import agent


def fake_model(request):
    packet = packet_response(request)
    if packet is not None:
        return packet
    content = json.loads(json.loads(request.content)["messages"][1]["content"])
    key = next(m["ref"] for m in content["messages"] if m["actor"] == "CUSTOMER")
    proposal = {
        "relationship": "merchant",
        "evidence": [key],
        "notes": [{"text": "关注英国线路成本", "evidence": [key]}],
        "batches": [
            {"origin": key, "text": "英国第一批", "stage": "needs", "evidence": [key]}
        ],
        "actions": [
            {
                "origin": key,
                "batch": key,
                "kind": "confirm_quote",
                "text": "确认英国报价",
                "reason": "商家明确有3方货",
                "state": "open",
                "owner": "platform",
                "evidence": [key],
            }
        ],
    }
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "proposal": proposal,
                                **({"checked": True} if "draft" in content else {}),
                            }
                        )
                    },
                }
            ],
            "usage": {"total_tokens": 50},
        },
    )


if __name__ == "__main__":
    os.environ["DEEPSEEK_API_KEY"] = "synthetic-workspace-test-key"
    app = create_app(Settings(data_dir=Path(os.environ["WA_BROWSER_DATA_DIR"])))
    db = app.state.db
    assert not db.rows("SELECT 1 FROM messages LIMIT 1"), (
        "Use a fresh fixture directory"
    )
    db.settings.bind_source("work")
    allow_conversation(
        db,
        "fixture",
        "work",
        "group",
        "英国三方群（虚构）",
        "group",
        None,
        None,
        True,
        followup_source=True,
    )
    configure(db, True)
    ingest(
        db,
        [
            {
                "source": "fixture",
                "account_id": "work",
                "conversation_id": "group",
                "conversation_type": "group",
                "source_id": "m1",
                "sender_id": "merchant",
                "direction": "incoming",
                "event_time": datetime.now(UTC).isoformat(),
                "message_type": "text",
                "text": "下周英国3方货，请确认报价。",
            }
        ],
    )
    with db.tx() as c:
        c.execute(
            "INSERT INTO identity_metadata VALUES('work','merchant','张先生（虚构）','张','',?)",
            (datetime.now(UTC).isoformat(),),
        )
    configure(db, False)  # Discovery must work before external analysis consent.
    agent.create_client = lambda: httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(fake_model)
    )
    uvicorn.run(app, host="127.0.0.1", port=8768, access_log=False)
