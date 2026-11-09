"""One budgeted, cached transport for packet extraction and customer synthesis."""

import json

import httpx

from ..analysis import Blocked, estimate_tokens, release_rejected, reserve, settle
from ..db import dumps, now
from ..model_network import connection_code
from .context import snapshot
from .quality import ENGINE_VERSION
from .store import stable


class Paused(Exception):
    pass


class ModelSession:
    def __init__(self, db, source_id, client, key, fingerprint, run_id, limit=12):
        self.db, self.source_id, self.client = db, source_id, client
        self.key, self.fingerprint, self.run_id = key, fingerprint, run_id
        self.limit, self.calls = limit, 0
        retries = db.rows(
            "SELECT id FROM events WHERE entity_id=? AND kind='workspace_retry' ORDER BY rowid DESC LIMIT 1",
            ("workspace-retry:" + stable(db.settings.source_account, source_id),),
        )
        self.retry_epoch = retries[0]["id"] if retries else None
        self.guard = None
        self.should_stop = None

    def ensure_active(self):
        if self.should_stop:
            if self.should_stop():
                raise Paused("automation_paused")
            self.db.heartbeat("worker", "workspace_running")
        if self.guard and not self.guard():
            raise ValueError("workspace_stale_input")

    def request(self, prompt, payload):
        db = self.db
        self.ensure_active()
        if self.guard is None and snapshot(db, self.source_id) != self.fingerprint:
            raise ValueError("workspace_stale_input")
        if len(dumps(payload)) > 90000:
            raise ValueError("workspace_context_limit")
        cache_key = stable(
            ENGINE_VERSION,
            db.settings.model,
            db.settings.source_account,
            self.source_id,
            self.retry_epoch,
            prompt,
            payload,
        )
        saved = db.rows(
            "SELECT response FROM model_responses WHERE cache_key=?", (cache_key,)
        )
        if saved:
            return json.loads(saved[0]["response"])
        if self.calls >= self.limit:
            raise Paused("call_limit")
        maximum = min(6000, db.settings.max_output_tokens)
        try:
            rid = reserve(
                db, self.run_id, estimate_tokens(prompt + dumps(payload)) + maximum
            )
        except Blocked as exc:
            if "budget" in exc.status:
                raise Paused(exc.status) from None
            raise
        self.calls += 1
        with db.tx() as c:
            c.execute(
                "UPDATE workspace_runs SET calls=calls+1 WHERE id=?", (self.run_id,)
            )
        try:
            response = self.client.post(
                "/chat/completions",
                headers={"Authorization": "Bearer " + self.key},
                json={
                    "model": db.settings.model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": dumps(payload)},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": maximum,
                    "stream": False,
                    "temperature": 0,
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError) as exc:
            release_rejected(db, rid)
            raise ValueError(connection_code(exc)) from None
        if response.status_code in {400, 401, 402, 403, 404, 422, 429}:
            release_rejected(db, rid)
        if response.status_code >= 400:
            raise ValueError("HTTP_" + str(response.status_code))
        data = response.json()
        settle(db, rid, data)
        with db.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO model_responses VALUES(?,?,?,?)",
                (cache_key, db.settings.model, dumps(data), now()),
            )
        return data

    def factbook(self, prompt, payload):
        from .schema import FactBook

        for attempt in range(3):
            data = self.request(
                prompt, payload | ({"repair_attempt": attempt} if attempt else {})
            )
            try:
                choice = data["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("incomplete")
                return FactBook.model_validate_json(choice["message"]["content"])
            except (ValueError, KeyError, IndexError, TypeError):
                if attempt == 2:
                    raise ValueError("workspace_fact_schema") from None
