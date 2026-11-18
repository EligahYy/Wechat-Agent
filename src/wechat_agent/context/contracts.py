from typing import Literal
from pydantic import AwareDatetime,BaseModel,ConfigDict,Field,field_validator
from ..source.contracts import ContactKey
from ..profiles.contracts import SourceRef

class SnapshotError(ValueError):
    """Explicit missing, unauthorized or invalid snapshot material."""

class ContextCoverage(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    required_conversation_ids:tuple[str,...]=()
    completed_conversation_ids:tuple[str,...]=()
    numberless_conversation_ids:tuple[str,...]=Field(default=(), exclude_if=lambda value: not value)
    warning_codes:tuple[str,...]=()
    policy_version:Literal['known-scope-v1']='known-scope-v1'

    @field_validator('required_conversation_ids','completed_conversation_ids','numberless_conversation_ids','warning_codes')
    @classmethod
    def canonical(cls,value):return tuple(sorted(set(value)))

class ContextSnapshot(BaseModel):
    coverage:ContextCoverage|None=None
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str
    key:ContactKey
    cutoff:AwareDatetime
    material_refs:tuple[SourceRef,...]
    role_version:int=Field(gt=0)
    manual_version:int=Field(ge=0)
    versions:dict[str,str]
    profile_version:int=Field(default=0,ge=0)
    scope_version:int=Field(default=0,ge=0)
    gaps:tuple[str,...]
