from typing import Literal
from pydantic import AwareDatetime,BaseModel,ConfigDict,Field
from ..source.contracts import ContactKey
from ..profiles.contracts import SourceRef

class DiscoverySnapshot(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str
    key:ContactKey
    cutoff:AwareDatetime
    purpose:Literal['discovery']='discovery'
    generation:str
    versions:dict[str,str]
    material_refs:tuple[SourceRef,...]
    gaps:tuple[str,...]

class DiscoveryResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    contact_id:str=Field(min_length=1)
    intent:Literal['request','advertisement','forwarded','other','uncertain']
    sources:list[SourceRef]=Field(min_length=1)
    gaps:list[str]=Field(default_factory=list)

class DiscoveryPublishResult(BaseModel):
    state:Literal['published','rejected','manual_excluded','stale','cancelled']
