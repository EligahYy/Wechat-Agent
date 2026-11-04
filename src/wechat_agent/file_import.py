"""Manual CSV/JSON/JSONL normalization; never invokes the old exporter."""

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import uid
from .ingestion import ingest
from .schemas import Message

MAX_BYTES = 64 * 1024 * 1024


def parse_text(text, filename, account=None):
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("文件超过 64 MB，请拆分导入")
    text = text.lstrip("\ufeff")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
    elif suffix in {".jsonl", ".ndjson"}:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif suffix == ".json":
        data = json.loads(text)
        rows = (
            data.get("messages", data.get("items")) if isinstance(data, dict) else data
        )
    else:
        raise ValueError("仅支持 CSV、JSON 数组／messages／items 和 JSONL")
    if not isinstance(rows, list):
        raise ValueError("文件不包含消息列表")
    records = []
    issues = []
    titles = {}
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError()
            if "conversation_username" in row:
                if not account:
                    raise ValueError()
                chat = str(row["conversation_username"]).strip()
                if not chat:
                    raise ValueError()
                server = str(row.get("server_id") or "").strip()
                if server in {"", "0", "None"}:
                    if not all(
                        str(row.get(k) or "").strip()
                        for k in ("db", "table", "local_id")
                    ):
                        raise ValueError()
                    server = (
                        "legacy:"
                        + hashlib.sha256(
                            json.dumps(
                                [row[k] for k in ("db", "table", "local_id")]
                            ).encode()
                        ).hexdigest()
                    )
                stamp = row.get("timestamp")
                if stamp not in (None, ""):
                    when = datetime.fromtimestamp(int(stamp), UTC)
                else:
                    when = datetime.fromisoformat(row["time"])
                    if when.utcoffset() is None:
                        when = when.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                kind = str(row.get("conversation_type", ""))
                if kind not in {"group", "direct", "private"}:
                    raise ValueError()
                code = row.get("type")
                label = str(row.get("type_name", "")).lower()
                is_text = str(code) == "1" or label in {"文本", "文字", "text"}
                is_image = str(code) == "3" or label in {"图片", "image"}
                direction = str(row.get("direction") or "unknown")
                if direction == "system":
                    direction = "unknown"
                sender = str(row.get("sender_username") or "unknown")
                record = dict(
                    source="wx_cli",
                    account_id=account,
                    conversation_id=chat,
                    conversation_type="group" if kind == "group" else "private",
                    source_id=server,
                    sender_id=sender,
                    direction=direction,
                    event_time=when.isoformat(),
                    message_type="text"
                    if is_text
                    else "3"
                    if is_image
                    else str(code or label or "unknown"),
                    text=str(row.get("content") or ""),
                    completeness="full" if is_text else "metadata",
                )
                titles[chat] = str(row.get("conversation") or chat)
            else:
                # Standard format retains explicit identity and source namespace.
                record = dict(row)
                if "schema_version" in record:
                    record["schema_version"] = int(record["schema_version"])
                if isinstance(record.get("source_locator"), str):
                    record["source_locator"] = json.loads(
                        record["source_locator"] or "{}"
                    )
                if account and not record.get("account_id"):
                    record["account_id"] = account
            validated = Message.model_validate(record)
            if account and validated.account_id != account:
                raise ValueError()
            records.append(validated.model_dump(mode="json"))
        except (ValueError, KeyError, TypeError, OverflowError):
            issues.append(
                {
                    "row": index,
                    "error": "字段、时间、账号或稳定消息ID不完整；未导入该行",
                }
            )
    return records, issues, titles


def import_file(db, text, filename, account=None, write=False):
    try:
        records, issues, titles = parse_text(
            text, filename, account or db.settings.source_account or None
        )
    except (ValueError, TypeError):
        raise ValueError("文件格式无法解析；请检查编码和消息结构") from None
    report = {
        "valid": len(records),
        "rejected": len(issues),
        "errors": issues[:50],
        "conversations": len(
            {(m["source"], m["account_id"], m["conversation_id"]) for m in records}
        ),
        "written": False,
    }
    if not write:
        return report
    if issues:
        raise ValueError(f"存在 {len(issues)} 行错误；请先预览并修正，本次未写入")
    counts = {"inserted": 0, "duplicates": 0, "revised": 0, "excluded": 0}
    # Explicit manual file grant creates local-only conversations. Full file is
    # transactional, batches only bound the ingestion validator's memory.
    with db.tx() as c:
        for m in records:
            old = c.execute(
                "SELECT id FROM conversations WHERE source=? AND account_id=? AND source_id=?",
                (m["source"], m["account_id"], m["conversation_id"]),
            ).fetchone()
            if not old:
                c.execute(
                    "INSERT INTO conversations(id,source,account_id,source_id,title,kind,allowlisted,egress) VALUES(?,?,?,?,?,?,1,0)",
                    (
                        uid(),
                        m["source"],
                        m["account_id"],
                        m["conversation_id"],
                        titles.get(m["conversation_id"], m["conversation_id"]),
                        m["conversation_type"],
                    ),
                )
            else:
                # Explicit import preserves pause, associations and egress policy;
                # historical ingestion itself never schedules model calls.
                pass
        for offset in range(0, len(records), 500):
            result = ingest(
                db, records[offset : offset + 500], analyze=False, connection=c
            )
            for key in counts:
                counts[key] += result[key]
        db.event(
            c,
            uid(),
            "manual_file_import",
            {"rows": len(records), "counts": counts, "external_calls": False},
        )
    if not db.settings.source_account and account:
        db.settings.bind_source(account)
    return report | counts | {"written": True}
