"""Strict model candidates; source authorization belongs to snapshot validation."""
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

class Candidate(BaseModel):
    model_config=ConfigDict(extra='forbid',validate_assignment=True)

class SourceRef(Candidate):
    message_id:str=Field(min_length=1,max_length=512)
    revision:StrictInt=Field(gt=0)
    attachment_id:str|None=None
    locator:str|None=None

    @field_validator('message_id')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('message_id_required')
        return value

class Fact(Candidate):
    value:str|None=Field(default=None,max_length=16000)
    state:Literal['known','uncertain','not_mentioned']='not_mentioned'
    sources:list[SourceRef]=Field(default_factory=list)
    event_time:AwareDatetime|None=None
    batch_ref:str|None=None

    @model_validator(mode='after')
    def evidence_required(self):
        if self.state=='not_mentioned':
            if self.value is not None or self.sources or self.event_time is not None or self.batch_ref is not None:
                raise ValueError('not_mentioned_must_be_empty')
        elif self.state=='known' and (not self.value or not self.value.strip() or not self.sources):
            raise ValueError('known_fact_requires_value_and_evidence')
        elif self.value is not None and (not self.value.strip() or not self.sources):
            raise ValueError('fact_value_requires_evidence')
        return self

class Goods(Candidate):
    category:Fact=Field(default_factory=Fact)
    products:Fact=Field(default_factory=Fact)
    special_attributes:Fact=Field(default_factory=Fact)
    volume:Fact=Field(default_factory=Fact)

class Logistics(Candidate):
    origins:Fact=Field(default_factory=Fact)
    destinations:Fact=Field(default_factory=Fact)
    warehouse_postcode:Fact=Field(default_factory=Fact)
    transport:Fact=Field(default_factory=Fact)
    clearance_tax:Fact=Field(default_factory=Fact)
    timing:Fact=Field(default_factory=Fact)
    price:Fact=Field(default_factory=Fact)
    pickup_lastmile:Fact=Field(default_factory=Fact)
    concerns:Fact=Field(default_factory=Fact)

Tag=Literal['初步沟通','需求沟通中','询价中','方案对接中','备货中','暂缓','暂无新需求记录']
class Communication(Candidate):
    summary:Fact=Field(default_factory=Fact)
    tags:list[Tag]=Field(default_factory=list)
    last_business_at:AwareDatetime|None=None

    @field_validator('tags')
    @classmethod
    def consistent_tags(cls,value):
        if len(set(value))!=len(value):raise ValueError('duplicate_communication_tags')
        if '暂无新需求记录' in value and set(value)&{'需求沟通中','询价中','方案对接中','备货中'}:
            raise ValueError('no_new_demand_conflicts_with_active_tags')
        return value

class ShipmentCandidate(Candidate):
    existing_id:str|None=Field(default=None,min_length=1,max_length=512)
    candidate_key:str=Field(min_length=1,max_length=512)
    goods:list[Fact]=Field(default_factory=list)
    logistics:list[Fact]=Field(default_factory=list)
    stage:Literal['沟通','询价','方案对接','备货','已走货','已结束','暂缓']
    numbers:list[str]=Field(default_factory=list)
    sources:list[SourceRef]=Field(default_factory=list)

    @field_validator('candidate_key','existing_id')
    @classmethod
    def identity_not_blank(cls,value):
        if value is not None and not value.strip():raise ValueError('batch_identity_required')
        return value

class AnalysisResult(Candidate):
    schema_version:Literal[1]=1
    contact_id:str=Field(min_length=1,max_length=512)
    goods:Goods=Field(default_factory=Goods)
    logistics:Logistics=Field(default_factory=Logistics)
    communication:Communication=Field(default_factory=Communication)
    shipments:list[ShipmentCandidate]=Field(default_factory=list)
    gaps:list[str]=Field(default_factory=list)

    @field_validator('contact_id')
    @classmethod
    def contact_required(cls,value):
        if not value.strip():raise ValueError('contact_id_required')
        return value


def analysis_result_schema() -> dict:
    """Fresh JSON Schema for the configured gateway; does not call a model."""
    return AnalysisResult.model_json_schema()
