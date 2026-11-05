"""Evidence-carrying model contract; the model never writes business state directly."""

from typing import Literal

from pydantic import Field

from .schemas import Strict


class Fact(Strict):
    field: Literal[
        "company",
        "market",
        "cargo",
        "volume",
        "timing",
        "concern",
        "preference",
        "summary",
    ]
    value: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=10)


class Person(Strict):
    actor_ref: str
    role: Literal["merchant", "service_provider", "other", "unknown"]
    facts: list[Fact] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(min_length=1, max_length=10)


class Action(Strict):
    customer_ref: str
    contact_ref: str | None = None
    action_key: str = Field(min_length=1, max_length=100)
    operation: Literal["create", "update", "complete", "cancel", "wait"]
    summary: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    opportunity: str = Field(default="", max_length=150)
    stage: Literal[
        "needs",
        "quoting",
        "decision",
        "preparing",
        "shipping",
        "reported_complete",
        "paused",
    ] = "needs"
    party: Literal["self", "merchant", "service_provider", "unknown"] = "self"
    due_text: str | None = Field(default=None, max_length=100)
    due_date: str | None = Field(default=None, max_length=10)
    date_kind: Literal["explicit", "suggested"] = "suggested"
    evidence_refs: list[str] = Field(min_length=1, max_length=15)


class Ambiguity(Strict):
    question: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=10)


class CRMResult(Strict):
    schema_version: Literal[2]
    people: list[Person] = Field(default_factory=list, max_length=20)
    actions: list[Action] = Field(default_factory=list, max_length=20)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=10)
