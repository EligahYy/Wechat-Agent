from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Strict):
    schema_version: Literal[1] = 1
    source: Literal["manual", "fixture", "wx_cli"]
    account_id: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)
    conversation_type: Literal["private", "group"]
    source_id: str = Field(min_length=1, max_length=300)
    sender_id: str = Field(min_length=1, max_length=200)
    direction: Literal["incoming", "outgoing", "unknown"]
    event_time: datetime
    message_type: str = Field(min_length=1, max_length=50)
    text: str = Field(max_length=100000)
    completeness: Literal["full", "partial", "metadata"] = "full"
    source_locator: dict[str, str] = Field(default_factory=dict)

    @field_validator("event_time")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value


class Suggestion(Strict):
    kind: Literal["task_create"]
    summary: str = Field(min_length=1, max_length=1000)
    responsible_party: Literal[
        "self", "merchant", "service_provider", "other", "unknown"
    ]
    due_text: str | None = Field(default=None, max_length=200)
    evidence_refs: list[str] = Field(min_length=1, max_length=30)


class AnalysisResult(Strict):
    schema_version: Literal[1]
    suggestions: list[Suggestion] = Field(max_length=50)


class DraftResult(Strict):
    text: str = Field(min_length=1, max_length=3000)
    evidence_refs: list[str] = Field(min_length=1, max_length=30)
