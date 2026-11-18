"""Shared scope and cancellation identity, independent of HTTP routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, computed_field, model_validator

from ..source.contracts import ContactKey


class OperationScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    account_id: str = Field(min_length=1)
    contact_id: str | None = None

    @model_validator(mode="after")
    def stable_scope(self):
        ContactKey(account_id=self.account_id, contact_id=self.contact_id or "scope-validation")
        if self.contact_id == "":
            raise ValueError("empty_contact_scope")
        return self


class CancellationToken(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    operation_id: str = Field(min_length=1)
    generation: int = Field(ge=1)


RunState = Literal["queued", "running", "stop_requested", "stopped", "succeeded", "failed"]


class SyncOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sample: StrictBool = False
    from_start: StrictBool = False
    page_size: StrictInt = Field(default=200, ge=1, le=500)
    max_pages: StrictInt = Field(default=1000, ge=1, le=10000)
    conversation_ids: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def sample_defaults(cls, value):
        if isinstance(value, dict) and value.get("sample") is True:
            value = dict(value)
            value.setdefault("page_size", 20)
            value.setdefault("max_pages", 2)
        return value

    @model_validator(mode="after")
    def bounded_selection(self):
        if self.sample and (self.page_size > 20 or self.max_pages > 2):
            raise ValueError("sample_limits_exceeded")
        if self.conversation_ids is not None:
            if not self.conversation_ids or any(not item.strip() or len(item)>512 for item in self.conversation_ids):
                raise ValueError("invalid_conversation_selection")
            object.__setattr__(self, "conversation_ids", sorted(set(self.conversation_ids)))
        return self


class OperationItem(BaseModel):
    id: str
    contact_id: str | None = None
    conversation_id: str | None = None
    state: RunState
    phase: str
    generation: int
    counts: dict[str, int] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    error_code: str | None = None
    role_version: int | None = None


from .reports import OperationReport


class Operation(BaseModel):
    contact_name_snapshot: str | None = None
    report: OperationReport | None = None
    id: str
    scope: OperationScope
    action: str
    state: RunState
    phase: str = "queued"
    generation: int = 1
    remaining: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None
    source_state: RunState | None = None
    options: SyncOptions | None = None
    history_complete: Literal[False] = False
    items: list[OperationItem] = Field(default_factory=list)
    created_at: str
    updated_at: str

    @computed_field
    @property
    def available_actions(self) -> list[str]:
        if self.action == 'sync_and_organize' and self.state in {'failed', 'stopped'} and self.error_code in {'analysis_budget_paused', 'operation_interrupted'}:
            return ['resume']
        return ["stop"] if self.state in {"queued", "running"} else []
