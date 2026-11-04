"""Read-only adapter for pandorafuture/wx-cli messages contract.

Actual macOS/version compatibility must be verified separately. A successful HTTP
request never establishes complete historical coverage.
"""

import os
from datetime import UTC, datetime

import httpx

from .db import now, uid
from .ingestion import ingest


class SourceError(ValueError):
    pass


class Collector:
    def __init__(self, db, client=None):
        self.db = db
        self.client = client or httpx.Client(
            base_url=db.settings.source_endpoint(),
            timeout=30,
            headers={"Authorization": "Bearer " + os.environ["WX_SOURCE_TOKEN"]}
            if os.environ.get("WX_SOURCE_TOKEN")
            else {},
            follow_redirects=False,
            trust_env=False,
        )

    def validate(self):
        r = self.client.get("/api/v1/health")
        r.raise_for_status()
        data = r.json()
        identity = data.get("current_account", {}).get("wxid")
        if data.get("ready") is not True:
            raise SourceError("source_not_ready")
        if (
            not identity
            or identity != self.db.settings.source_account
            or identity != self.db.settings.self_id
        ):
            raise SourceError("source_account_mismatch_or_unconfigured")
        return {
            "health": "ready",
            "account_binding": "matched",
            "source_version": data.get("cli_version"),
            "capabilities": "full content and paging require sync test",
        }

    def sync_window(self, chat, since, until):
        if until < since or until - since > 86400:
            raise SourceError("窗口必须递增且不超过 24 小时")
        if chat["source"] != "wx_cli" or not chat["allowlisted"]:
            raise SourceError("非采集白名单会话")
        if (
            not self.db.settings.source_account
            or chat["account_id"] != self.db.settings.source_account
        ):
            raise SourceError(
                "WX_ACCOUNT_ID 缺失或账号绑定不匹配；源端账号身份仍需人工核对"
            )
        window_id = uid()
        records = []
        offset = 0
        seen = set()
        error = None
        try:
            self.validate()
            for _ in range(100):
                r = self.client.get(
                    "/api/v1/messages",
                    params={
                        "contact": chat["source_id"],
                        "since": since,
                        "until": until,
                        "order": "asc",
                        "limit": 200,
                        "offset": offset,
                    },
                )
                r.raise_for_status()
                envelope = r.json()
                stats = envelope.get("stats", {})
                if stats.get("skipped", 0) or stats.get("shard_warnings"):
                    raise SourceError("source_partial_shards")
                items = envelope["items"]
                paging = envelope["paging"]
                if not isinstance(items, list) or not isinstance(
                    paging.get("has_more"), bool
                ):
                    raise SourceError("invalid_paging")
                for item in items:
                    # EnrichedMessage flattens raw Message fields in the audited version.
                    raw = item.get("message", item)
                    if raw.get("talker") != chat["source_id"]:
                        raise SourceError("conversation_mismatch")
                    source_id = raw.get("server_id")
                    if source_id in (None, 0, "0", ""):
                        raise SourceError("stable_server_id_unavailable")
                    if str(source_id) in seen:
                        raise SourceError("unstable_paging_duplicate")
                    seen.add(str(source_id))
                    # Never promote snippet to full text.
                    content = raw.get("content")
                    text = content.get("Text") if isinstance(content, dict) else content
                    if raw.get("msg_type") == 1 and not isinstance(text, str):
                        raise SourceError("full_content_unavailable")
                    if raw.get("msg_type") != 1:
                        text = "[非文本消息：未解析正文]"
                    stamp = int(raw["create_time"])
                    if stamp < since or stamp > until:
                        raise SourceError("out_of_window")
                    sender = str(raw.get("sender", ""))
                    if not sender:
                        raise SourceError("sender_unavailable")
                    direction = (
                        "outgoing"
                        if sender == self.db.settings.self_id
                        else ("incoming" if self.db.settings.self_id else "unknown")
                    )
                    records.append(
                        dict(
                            schema_version=1,
                            source="wx_cli",
                            account_id=chat["account_id"],
                            conversation_id=chat["source_id"],
                            conversation_type=chat["kind"],
                            source_id=str(source_id),
                            sender_id=sender,
                            direction=direction,
                            event_time=datetime.fromtimestamp(stamp, UTC).isoformat(),
                            message_type="text"
                            if raw.get("msg_type") == 1
                            else str(raw.get("msg_type", "unknown")),
                            text=text,
                            completeness="full"
                            if raw.get("msg_type") == 1
                            else "metadata",
                        )
                    )
                if not paging["has_more"]:
                    break
                if not items:
                    raise SourceError("empty_page_with_more")
                offset += len(items)
            else:
                raise SourceError("pagination_limit")
            # Entire window must validate before any insert; ingest in one atomic batch.
            if len(records) > 1000:
                raise SourceError("window_too_large_split_required")
            result = ingest(self.db, records)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            error = str(exc) if isinstance(exc, SourceError) else type(exc).__name__
            result = {"error": error}
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO sync_windows VALUES(?,?,?,?,?,?,?)",
                (
                    window_id,
                    chat["id"],
                    since,
                    until,
                    "gap" if error else "scanned",
                    error,
                    now(),
                ),
            )
        self.db.heartbeat(
            "collector", "gap" if error else "scanned_not_guaranteed_complete"
        )
        return result

    def tick(self):
        results = []
        end = int(datetime.now(UTC).timestamp())
        for chat in self.db.rows(
            "SELECT * FROM conversations WHERE source='wx_cli' AND allowlisted=1"
        ):
            last = self.db.rows(
                "SELECT until FROM sync_windows WHERE conversation_id=? AND status='scanned' ORDER BY until DESC LIMIT 1",
                (chat["id"],),
            )
            start = (last[0]["until"] - 900) if last else end - 900
            # Bounded windows catch up without skipping downtime. Old gaps remain visible.
            for _ in range(6):
                until = min(start + 300, end)
                result = self.sync_window(chat, start, until)
                results.append(result)
                if "error" in result or until >= end:
                    break
                start = until
        return results
