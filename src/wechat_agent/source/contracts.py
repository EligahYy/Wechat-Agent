"""Application contracts, independent of the third-party wx-cli wire format."""

from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ContactKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    account_id: str = Field(min_length=1)
    contact_id: str = Field(min_length=1)

    @field_validator("account_id", "contact_id")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_identifier")
        return value

    @field_validator("contact_id")
    @classmethod
    def person_only(cls, value: str) -> str:
        if value.endswith("@chatroom"):
            raise ValueError("group_is_not_person")
        return value


class ContactRecord(BaseModel):
    key: ContactKey
    remark: str | None
    nickname: str | None
    is_self: bool


class ConversationRecord(BaseModel):
    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    kind: Literal["private", "group"]
    title: str | None
    member_ids: list[str] = Field(default_factory=list)


class MessageRecord(BaseModel):
    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    sent_at: AwareDatetime
    kind: str
    body: str
    reply_to: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    source_revision: str = Field(min_length=1)
    raw: dict


class SourcePage(BaseModel):
    account_id: str
    conversation_id: str
    records: list[MessageRecord]
    next_cursor: str | None
    complete: bool
    gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_scope(self):
        if any(r.account_id != self.account_id or r.conversation_id != self.conversation_id
               for r in self.records):
            raise ValueError("page_scope_mismatch")
        if self.complete and (self.next_cursor is not None or self.gaps):
            raise ValueError("incomplete_page_cannot_claim_complete")
        return self


class AttachmentFetch(BaseModel):
    attachment_id: str
    state: Literal["original", "thumbnail", "missing", "unavailable", "failed"]
    content: bytes | None
    mime: str | None
    reason: str | None


class CapabilityReport(BaseModel):
    component: str
    status: Literal["passed", "failed", "pending", "unsupported"]
    facts: dict = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    checked_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceAdapter(Protocol):
    async def check(self) -> CapabilityReport: ...
    async def contacts(self) -> list[ContactRecord]: ...
    async def conversations(self) -> list[ConversationRecord]: ...
    async def messages(self, conversation_id: str, cursor: str | None, limit: int) -> SourcePage: ...
    async def fetch_attachment(self, attachment_id: str) -> AttachmentFetch: ...
