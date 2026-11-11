"""Third-party pandorafuture/wx-cli v0.7.4 read protocol (upstream 7bed9e7)."""

from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote

from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationInfo, field_validator, model_validator

from .contracts import MessageRecord


class Account(BaseModel):
    wxid: str = Field(min_length=1)
    name: str = ""


class Health(BaseModel):
    ready: StrictBool
    worker_id: str = Field(min_length=1)
    cli_version: str = Field(min_length=1)
    current_account: Account


class Paging(BaseModel):
    limit: int = Field(gt=0, le=20000)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    has_more: StrictBool
    total: int = Field(ge=0)


class Stats(BaseModel):
    scanned: int = Field(ge=0)
    skipped: int = Field(ge=0)
    shard_warnings: list[dict] = Field(default_factory=list)


class Envelope(BaseModel):
    items: list[dict]
    paging: Paging
    stats: Stats

    @model_validator(mode="after")
    def consistent_count(self):
        if self.paging.returned != len(self.items):
            raise ValueError("returned_count_mismatch")
        return self


class WireMessage(BaseModel):
    sort_seq: StrictInt
    server_id: StrictInt
    msg_type: StrictInt
    sub_type: StrictInt
    sender: str
    talker: str = Field(min_length=1)
    create_time: StrictInt
    content: dict | str
    status: StrictInt

    @field_validator("sender")
    @classmethod
    def event_or_person_sender(cls, value: str, info: ValidationInfo):
        if (not value.strip() or value.endswith("@chatroom")) and info.data.get("msg_type") not in {10000, 10002}:
            raise ValueError("blank_source_sender")
        return value

    @field_validator("talker")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank_source_identity")
        return value


def parse_message(raw: dict, account_id: str) -> MessageRecord:
    row = WireMessage.model_validate(raw)
    if row.server_id <= 0:
        raise ValueError("message_id_unavailable")
    kind = {1: "text", 3: "image", 34: "voice", 43: "video", 10000: "system", 10002: "revoke"}.get(row.msg_type, "unknown")
    if row.msg_type == 49:
        kind = {6: "file", 57: "quote", 19: "merged_messages"}.get(row.sub_type, "app")
    content = row.content
    if isinstance(content, str):
        body = content
    elif isinstance(content.get("Text"), str):
        body = content["Text"]
    elif kind == "system" and isinstance(content.get("System"), str):
        body = content["System"]
    elif kind == "revoke" and isinstance(content.get("Revoke"), str):
        body = content["Revoke"]
    elif isinstance(content.get("Quote"), dict):
        body = content["Quote"].get("reply_text") or ""
    elif isinstance(content.get("File"), dict):
        body = content["File"].get("title") or ""
    else:
        body = json.dumps(content, ensure_ascii=False)
    identity = f"wx-cli:{quote(row.talker, safe='')}:{row.server_id}"
    return MessageRecord(
        account_id=account_id, conversation_id=row.talker, message_id=identity,
        sender_id=row.sender if row.sender.strip() and not row.sender.endswith("@chatroom") else None,
        sent_at=datetime.fromtimestamp(row.create_time, timezone.utc),
        kind=kind, body=body,
        attachment_ids=[f"media:{identity}"] if kind in {"image", "voice", "video", "file"} else [],
        source_revision=hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        raw=raw,
    )
