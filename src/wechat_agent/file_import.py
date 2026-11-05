"""One optional file-import path using the standard message schema."""

import csv
import io
import json
from pathlib import Path

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
            record = dict(row)
            if "schema_version" in record:
                record["schema_version"] = int(record["schema_version"])
            if isinstance(record.get("source_locator"), str):
                record["source_locator"] = json.loads(record["source_locator"] or "{}")
            if account and not record.get("account_id"):
                record["account_id"] = account
            record.setdefault("source", "manual")
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
    # New conversations may inherit the account's explicit include-new grant.
    # File writes are transactional; analysis runs separately on the queue.
    with db.tx() as c:
        for m in records:
            old = c.execute(
                "SELECT id FROM conversations WHERE source=? AND account_id=? AND source_id=?",
                (m["source"], m["account_id"], m["conversation_id"]),
            ).fetchone()
            if not old:
                policy = c.execute(
                    "SELECT enabled,include_new FROM crm_policies WHERE account_id=?",
                    (m["account_id"],),
                ).fetchone()
                grant = int(
                    bool(policy and policy["enabled"] and policy["include_new"])
                )
                c.execute(
                    "INSERT INTO conversations(id,source,account_id,source_id,title,kind,allowlisted,egress,followup_source) VALUES(?,?,?,?,?,?,1,?,1)",
                    (
                        uid(),
                        m["source"],
                        m["account_id"],
                        m["conversation_id"],
                        titles.get(m["conversation_id"], m["conversation_id"]),
                        m["conversation_type"],
                        grant,
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
    from .crm import schedule

    schedule(db)
    return report | counts | {"written": True}
