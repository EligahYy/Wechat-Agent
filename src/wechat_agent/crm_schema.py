"""Evidence-carrying model contract; the model never writes business state directly."""

from typing import Literal, get_args

from pydantic import Field, field_validator

from .schemas import Strict

Party = Literal["self", "merchant", "service_provider", "other", "unknown"]
PARTY_VALUES = get_args(Party)
# Only deterministic role labels; names/IDs, multi-owner labels and arbitrary
# values remain invalid. This never changes actor or evidence references.
PARTY_ALIASES = {
    "platform": "self",
    "operator": "self",
    "platform_operator": "self",
    "platform_operations": "self",
    "我": "self",
    "我方": "self",
    "平台": "self",
    "运营": "self",
    "平台运营": "self",
    "customer": "merchant",
    "seller": "merchant",
    "商家": "merchant",
    "客户": "merchant",
    "provider": "service_provider",
    "logistics_provider": "service_provider",
    "logistics": "service_provider",
    "服务商": "service_provider",
    "物流服务商": "service_provider",
    "物流商": "service_provider",
    "头程服务商": "service_provider",
    "third_party": "other",
    "other_party": "other",
    "其他": "other",
    "第三方": "other",
    "未知": "unknown",
    "不明": "unknown",
    "待确认": "unknown",
    "未明确": "unknown",
}


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
    party: Party = "unknown"
    due_text: str | None = Field(default=None, max_length=100)
    due_date: str | None = Field(default=None, max_length=10)
    date_kind: Literal["explicit", "suggested"] = "suggested"
    evidence_refs: list[str] = Field(min_length=1, max_length=15)

    @field_validator("party", mode="before")
    @classmethod
    def normalize_party(cls, value):
        if value is None:
            return "unknown"
        if isinstance(value, str):
            normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
            return (
                PARTY_ALIASES.get(normalized, normalized) if normalized else "unknown"
            )
        return value


class Ambiguity(Strict):
    question: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=10)


class CRMResult(Strict):
    schema_version: Literal[2]
    people: list[Person] = Field(default_factory=list, max_length=20)
    actions: list[Action] = Field(default_factory=list, max_length=20)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=10)
