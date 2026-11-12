"""Application contracts, independent of the third-party wx-cli wire format."""

from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from ..identities import is_person_identifier


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
    remark_state: Literal['known', 'empty', 'unreadable', 'unknown'] = 'unknown'
    nickname_state: Literal['known', 'empty', 'unreadable', 'unknown'] = 'unknown'

    @model_validator(mode='before')
    @classmethod
    def explicit_internal_names(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            for field in ('remark', 'nickname'):
                value.setdefault(field + '_state', 'known' if value.get(field) else 'empty')
        return value


class NameEvidence(BaseModel):
    contact_id: str = Field(min_length=1)
    origin: Literal['group_member', 'session_sender']
    conversation_id: str = Field(min_length=1)
    value: str | None
    state: Literal['known', 'empty', 'unreadable', 'unknown']
    observed_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def valid_evidence(self):
        if not is_person_identifier(self.contact_id):
            raise ValueError('invalid_name_identity')
        if self.state == 'known' and not self.value:
            raise ValueError('known_name_requires_value')
        return self


class ConversationRecord(BaseModel):
    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    kind: Literal["private", "group"]
    title: str | None
    origin: Literal['session', 'metadata_candidate', 'group_directory', 'unknown'] = 'unknown'
    member_ids: list[str] = Field(default_factory=list)
    membership_state: Literal['known', 'empty', 'unreadable', 'unknown'] = 'unknown'
    name_evidence: list[NameEvidence] = Field(default_factory=list)

    @model_validator(mode='after')
    def names_match_scope(self):
        if any(name.conversation_id != self.conversation_id for name in self.name_evidence):
            raise ValueError('name_conversation_mismatch')
        if self.kind != 'group' and any(name.origin == 'group_member' for name in self.name_evidence):
            raise ValueError('group_name_requires_group')
        return self


class MessageRecord(BaseModel):
    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    # Only system/revoke events may have no person attribution.
    sender_id: str | None = Field(min_length=1)
    sent_at: AwareDatetime
    kind: str
    body: str
    reply_to: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    source_revision: str = Field(min_length=1)
    raw: dict

    @model_validator(mode="after")
    def valid_sender(self):
        if self.sender_id is None:
            if self.kind not in {"system", "revoke"}:
                raise ValueError("person_message_sender_required")
        elif not self.sender_id.strip():
            raise ValueError("blank_message_sender")
        elif self.sender_id.endswith("@chatroom"):
            raise ValueError("group_is_not_person")
        elif not is_person_identifier(self.sender_id):
            raise ValueError("invalid_source_sender")
        return self


class SourceIssue(BaseModel):
    code: Literal["message_sender_missing", "message_sender_invalid", "message_sender_conflict", "source_message_id_unavailable", "message_contract_invalid"]
    message_id: str | None = None
    raw: dict


class SourcePage(BaseModel):
    account_id: str
    conversation_id: str
    conversation_kind: Literal["private", "group"] | None = None
    records: list[MessageRecord]
    next_cursor: str | None
    complete: bool
    gaps: list[str] = Field(default_factory=list)
    issues: list[SourceIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_scope(self):
        if any(r.account_id != self.account_id or r.conversation_id != self.conversation_id
               for r in self.records):
            raise ValueError("page_scope_mismatch")
        if self.complete and (self.next_cursor is not None or self.gaps):
            raise ValueError("incomplete_page_cannot_claim_complete")
        if any(issue.code not in self.gaps for issue in self.issues):
            raise ValueError("unreported_source_issue")
        if any(issue.raw.get("talker") != self.conversation_id for issue in self.issues):
            raise ValueError("source_issue_scope_mismatch")
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
    @property
    def account_id(self) -> str: ...
    async def check(self) -> CapabilityReport: ...
    async def contacts(self) -> list[ContactRecord]: ...
    async def conversations(self) -> list[ConversationRecord]: ...
    async def messages(self, conversation_id: str, cursor: str | None, limit: int) -> SourcePage: ...
    async def fetch_attachment(self, attachment_id: str) -> AttachmentFetch: ...
