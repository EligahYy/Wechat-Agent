from typing import Literal

from pydantic import Field

from ..schemas import Strict


class Item(Strict):
    text: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(min_length=1, max_length=12)


class Batch(Item):
    ref: str | None = None
    origin: str
    stage: Literal[
        "needs",
        "quoting",
        "decision",
        "preparing",
        "fulfillment",
        "reported_shipped",
        "closed",
    ]


class Action(Item):
    ref: str | None = None
    batch: str | None = None
    origin: str
    kind: Literal["callback", "confirm_demand", "confirm_quote", "prepare_shipment"]
    state: Literal["open", "waiting", "done", "cancelled"]
    owner: Literal["platform", "customer", "provider", "unknown"] = "unknown"
    due_date: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class Decision(Item):
    key: Literal["role", "batch", "timing", "other"]
    blocks_followup: bool = False
    impact: str = Field(default="", max_length=500)


class Proposal(Strict):
    relationship: Literal["merchant", "candidate", "non_target"]
    evidence: list[str] = Field(min_length=1, max_length=12)
    notes: list[Item] = Field(default_factory=list, max_length=12)
    batches: list[Batch] = Field(default_factory=list, max_length=8)
    actions: list[Action] = Field(default_factory=list, max_length=8)
    decisions: list[Decision] = Field(default_factory=list, max_length=4)


class Turn(Strict):
    search: str | None = Field(default=None, max_length=80)
    proposal: Proposal | None = None


class Review(Strict):
    proposal: Proposal
    checked: Literal[True]


class Fact(Item):
    kind: Literal[
        "identity",
        "need",
        "quote",
        "shipment",
        "commitment",
        "reply",
        "context",
        "uncertainty",
    ]
    order_id: str | None = Field(default=None, max_length=100)
    subject: Literal["customer", "other", "unclear"] = "unclear"


class FactBook(Strict):
    facts: list[Fact] = Field(max_length=80)
