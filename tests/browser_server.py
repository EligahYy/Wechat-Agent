"""Optional Chromium smoke server; only synthetic upstream, isolated DB."""

import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from test_source_setup import source_response

from wechat_agent.cli import seed_demo
from wechat_agent.collector import Collector
from wechat_agent.config import Settings
from wechat_agent.web import create_app

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lWQAAAAASUVORK5CYII="
)


def with_image(request):
    if request.url.path.endswith("/media"):
        return httpx.Response(
            200, content=PNG, headers={"x-wechat-media-quality": "thumbnail"}
        )
    response = source_response(request)
    if request.url.path.endswith("/messages"):
        body = response.json()
        body["items"].append(
            {
                "talker": request.url.params["contact"],
                "server_id": "101",
                "sender": "merchant",
                "msg_type": 3,
                "create_time": int(datetime.now(UTC).timestamp()),
                "content": {"Image": {"md5": "a" * 32}},
            }
        )
        return httpx.Response(200, json=body)
    return response


def factory(db):
    return Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100",
            transport=httpx.MockTransport(with_image),
        ),
    )


if __name__ == "__main__":
    directory = os.environ.get("WA_BROWSER_DATA_DIR")
    if not directory:
        raise SystemExit("Set WA_BROWSER_DATA_DIR to an isolated, empty test directory")
    settings = Settings(data_dir=Path(directory))
    app = create_app(settings, source_factory=factory)
    if not app.state.db.rows("SELECT 1 FROM merchants LIMIT 1"):
        seed_demo(app.state.db)
    uvicorn.run(app, host="127.0.0.1", port=8767, access_log=False)
