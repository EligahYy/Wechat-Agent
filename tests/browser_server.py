"""Isolated browser fixture. Both upstreams and every customer are synthetic."""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from test_source_setup import source_response

from wechat_agent.analysis import run_once
from wechat_agent.collector import Collector
from wechat_agent.config import Settings
from wechat_agent.crm import configure, stable_actor
from wechat_agent.db import now, uid
from wechat_agent.ingestion import ingest
from wechat_agent.services import allow_conversation
from wechat_agent.web import create_app

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lWQAAAAASUVORK5CYII="
)


def upstream(req):
    if req.url.path.endswith("/media"):
        return httpx.Response(
            200, content=PNG, headers={"x-wechat-media-quality": "thumbnail"}
        )
    return source_response(req)


def factory(db):
    return Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(upstream)
        ),
    )


def fixture(settings):
    os.environ["DEEPSEEK_API_KEY"] = "synthetic-browser-key"
    app = create_app(settings, source_factory=factory)
    db = app.state.db
    if db.rows("SELECT 1 FROM messages LIMIT 1"):
        raise ValueError("Browser test requires an empty isolated directory")
    db.settings.bind_source("work-account")
    allow_conversation(
        db,
        "wx_cli",
        "work-account",
        "merchant",
        "示例商家（虚构）",
        "private",
        None,
        None,
        False,
        followup_source=True,
    )
    stamp = datetime.now(UTC).isoformat()
    base = {
        "source": "wx_cli",
        "account_id": "work-account",
        "conversation_id": "merchant",
        "conversation_type": "private",
        "sender_id": "merchant",
        "direction": "incoming",
        "event_time": stamp,
        "message_type": "text",
    }
    ingest(
        db,
        [
            base | {"source_id": "1", "text": "美国普货3方，请今天确认这批附加费。"},
            base
            | {
                "source_id": "2",
                "text": "收到",
                "event_time": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            },
            base
            | {
                "source_id": "3",
                "text": "[图片]",
                "message_type": "3",
                "completeness": "metadata",
                "source_locator": {"image_md5": "a" * 32},
            },
        ],
    )
    configure(db, True)
    actor = stable_actor("work-account", "merchant")
    result = {
        "schema_version": 2,
        "people": [
            {
                "actor_ref": actor,
                "role": "merchant",
                "facts": [
                    {"field": "market", "value": "美国", "evidence_refs": ["E001"]},
                    {"field": "volume", "value": "3方", "evidence_refs": ["E001"]},
                ],
                "evidence_refs": ["E001"],
            }
        ],
        "actions": [
            {
                "customer_ref": actor,
                "action_key": "附加费",
                "summary": "确认本批头程附加费",
                "reason": "商家在等待报价条件",
                "operation": "create",
                "opportunity": "美国普通货本批需求",
                "stage": "quoting",
                "party": "platform_operator",
                "due_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                "due_text": "今天",
                "date_kind": "explicit",
                "evidence_refs": ["E001"],
            }
        ],
        "ambiguities": [],
    }
    client = httpx.Client(
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(result)},
                        }
                    ],
                    "usage": {"total_tokens": 100},
                },
            )
        ),
    )
    while run_once(db, client):
        pass
    client.close()
    # Synthetic usage exercises the chart's distinct reported/reserved series.
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    with db.tx() as c:
        for offset, reported, uncertain in [
            (6, 2300, 0),
            (3, 5200, 12000),
            (1, 8500, 0),
            (0, 17555, 98680),
        ]:
            day = (today - timedelta(days=offset)).isoformat()
            c.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
                (uid(), None, day, reported, reported, "reported", now()),
            )
            if uncertain:
                c.execute(
                    "INSERT INTO usage VALUES(?,?,?,?,?,?,?)",
                    (uid(), None, day, uncertain, None, "unknown", now()),
                )
    return app


if __name__ == "__main__":
    directory = os.environ.get("WA_BROWSER_DATA_DIR")
    if not directory:
        raise SystemExit("Set WA_BROWSER_DATA_DIR to a new isolated test directory")
    uvicorn.run(
        fixture(Settings(data_dir=Path(directory))),
        host="127.0.0.1",
        port=8767,
        access_log=False,
    )
