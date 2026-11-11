"""Shared scope and cancellation identity, independent of HTTP routes."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
