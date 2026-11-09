"""Local-only new workspace browser fixture, with synthetic data and model."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from model_packets import packet_response
from test_media import PNG

from wechat_agent.collector import Collector
from wechat_agent.config import Settings
from wechat_agent.crm import configure
from wechat_agent.ingestion import ingest
from wechat_agent.services import allow_conversation
from wechat_agent.web import create_app
from wechat_agent.workspace import agent, drafts, ocr


def fake_model(request):
    packet = packet_response(request)
    if packet is not None:
        return packet
    content = json.loads(json.loads(request.content)["messages"][1]["content"])
    key = next(m["ref"] for m in content["messages"] if m["actor"] == "CUSTOMER")
    if "action" in content:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "text": "您好，想了解这批英国货的报价进展，方便时请回复。",
                                    "evidence": [key],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )
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

    def source_factory(store):
        def source_response(request):
            if request.url.path.endswith("/health"):
                return httpx.Response(
                    200, json={"ready": True, "current_account": {"wxid": "work"}}
                )
            return httpx.Response(
                200, content=PNG, headers={"x-wechat-media-quality": "thumbnail"}
            )

        return Collector(
            store,
            httpx.Client(
                base_url="http://127.0.0.1:9100",
                transport=httpx.MockTransport(source_response),
            ),
        )

    app = create_app(
        Settings(data_dir=Path(os.environ["WA_BROWSER_DATA_DIR"])),
        source_factory=source_factory,
    )

    @app.middleware("http")
    async def navigation_metadata(request, call_next):
        response = await call_next(request)
        if request.url.path in {
            "/",
            "/workspace",
            "/workspace/",
            "/legacy",
            "/legacy/",
        }:
            response.headers["X-Test-Fetch-Site"] = request.headers.get(
                "sec-fetch-site", "missing"
            )
        return response

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

    drafts.create_client = agent.create_client
    ocr.recognize_bytes = lambda data: ("海运报价候选，需核对原图", "synthetic-local")

    @app.post("/__test__/review-fixture")
    def review_fixture(role: bool = False):
        from wechat_agent.db import dumps, now
        from wechat_agent.workspace.context import build
        from wechat_agent.workspace.store import raw, read, reference, save, stable

        ingest(
            db,
            [
                {
                    "source": "fixture",
                    "account_id": "work",
                    "conversation_id": "group",
                    "conversation_type": "group",
                    "source_id": "self1",
                    "sender_id": "work",
                    "direction": "outgoing",
                    "event_time": datetime.now(UTC).isoformat(),
                    "message_type": "text",
                    "text": "我方已对接卡航，等待确认报价。",
                }
            ],
        )
        agent.run(db, "merchant")
        ctx = build(db, "merchant")
        own_key, own = next(
            (k, v) for k, v in ctx["evidence"].items() if v["direction"] == "outgoing"
        )
        anchor = next(v for v in ctx["evidence"].values() if v["anchor"])
        doc = read(db, "merchant")
        body = doc["body"]
        body["unattributed"] = [
            {
                "section": "notes",
                "code": "workspace_customer_anchor_required",
                "text": "SELF已对接卡航，客户的意向待核实",
                "evidence": [reference(anchor), reference(own)],
            },
            {
                "section": "notes",
                "code": "workspace_customer_anchor_required",
                "text": "客户货型是否服装，需要核对",
                "evidence": [reference(anchor)],
            },
        ]
        body["quality_issues"] = [
            {"section": "notes", "code": "workspace_customer_anchor_required"}
        ] * 2
        if role:
            body["decisions"]["role"] = {
                "text": "确认当前联系人身份（虚构）",
                "evidence": [reference(anchor)],
                "resolved": False,
            }

        with db.tx() as c:
            save(
                c,
                db,
                "merchant",
                body,
                json.loads(raw(db, "merchant")["read_set"]),
                doc["version"] + 1,
                "fixture",
            )
            c.execute(
                "INSERT INTO workspace_packets VALUES(?,?,?,?,?,?,?)",
                (
                    stable("self-fixture"),
                    "work",
                    "merchant",
                    "extract",
                    dumps([reference(own)]),
                    dumps(
                        {
                            "facts": [
                                {
                                    "subject": "other",
                                    "kind": "quote",
                                    "text": "SELF提到卡航，等待报价反馈",
                                    "evidence": [own_key],
                                }
                            ]
                        }
                    ),
                    now(),
                ),
            )
        return {"ok": True}

    @app.post("/__test__/add-image")
    def add_image():
        allow_conversation(
            db,
            "wx_cli",
            "work",
            "merchant",
            "张先生私信（虚构）",
            "private",
            None,
            None,
            True,
            followup_source=True,
        )
        ingest(
            db,
            [
                {
                    "source": "wx_cli",
                    "account_id": "work",
                    "conversation_id": "merchant",
                    "conversation_type": "private",
                    "source_id": "image1",
                    "sender_id": "merchant",
                    "direction": "incoming",
                    "event_time": datetime.now(UTC).isoformat(),
                    "message_type": "3",
                    "text": "[图片]",
                    "completeness": "metadata",
                    "source_locator": {"image_md5": "a" * 32},
                }
            ],
        )
        return {"ok": True}

    @app.post("/__test__/advance-queue")
    def advance_queue():
        from wechat_agent.workspace.queue import step

        ingest(
            db,
            [
                {
                    "source": "fixture",
                    "account_id": "work",
                    "conversation_id": "group",
                    "conversation_type": "group",
                    "source_id": "m2",
                    "sender_id": "merchant",
                    "direction": "incoming",
                    "event_time": datetime.now(UTC).isoformat(),
                    "message_type": "text",
                    "text": "补充该客户的最新沟通记录",
                }
            ],
        )
        return {"worked": step(db)}

    uvicorn.run(app, host="127.0.0.1", port=8768, access_log=False)
