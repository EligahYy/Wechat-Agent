from pydantic import AwareDatetime,BaseModel,ConfigDict,Field
from ..source.contracts import ContactKey
from ..profiles.contracts import SourceRef

class SnapshotError(ValueError):
    """Explicit missing, unauthorized or invalid snapshot material."""

class ContextSnapshot(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str
    key:ContactKey
    cutoff:AwareDatetime
    material_refs:tuple[SourceRef,...]
    role_version:int=Field(gt=0)
    manual_version:int=Field(ge=0)
    versions:dict[str,str]
    gaps:tuple[str,...]
