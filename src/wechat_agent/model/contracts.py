"""Verified capabilities are distinct from values declared in a probe config."""

from pydantic import AwareDatetime, BaseModel, Field, StrictBool, field_validator, model_validator


class ModelCapabilities(BaseModel):
    model_id: str = Field(min_length=1)
    context_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    structured_output: StrictBool
    vision: StrictBool
    verified_at: AwareDatetime

    @model_validator(mode="after")
    def output_fits_context(self):
        if self.max_output_tokens > self.context_tokens:
            raise ValueError("output_limit_exceeds_context")
        return self

from typing import Literal
from .probe import ModelProbeConfig

class ModelCallError(Exception):
    def __init__(self,code:str,message:str='模型请求未完成'):
        self.code=code
        super().__init__(message)

class ModelConfig(BaseModel):
    model_config={'extra':'forbid','frozen':True}
    version:str=Field(min_length=1)
    endpoint:str
    model_id:str=Field(min_length=1)
    credential_ref:str=Field(min_length=1)
    response_mode:Literal['text','json_object','json_schema']='json_object'
    capabilities:ModelCapabilities

    @field_validator('endpoint')
    @classmethod
    def safe_endpoint(cls,value):return ModelProbeConfig.credential_safe_endpoint(value)

    @model_validator(mode='after')
    def same_model(self):
        if self.model_id!=self.capabilities.model_id:raise ValueError('capabilities_model_mismatch')
        if self.response_mode=='json_schema' and not self.capabilities.structured_output:raise ValueError('schema_mode_not_verified')
        return self

class ModelMessage(BaseModel):
    model_config={'extra':'forbid'}
    role:Literal['system','user','assistant']
    content:str

class ModelRequest(BaseModel):
    checkpoint_key:str|None=Field(default=None,min_length=1,max_length=64)
    model_config={'extra':'forbid'}
    call_id:str=Field(min_length=1,max_length=128)
    unit_id:str=Field(min_length=1,max_length=128)
    snapshot_id:str=Field(min_length=1)
    purpose:Literal['profile','discovery']='profile'
    phase:Literal['extract','merge','verify']
    model_config_version:str=Field(min_length=1)
    messages:list[ModelMessage]=Field(min_length=1)
    output_schema:dict
    output_tokens:int=Field(gt=0)

class ModelResponse(BaseModel):
    payload:dict
    finish_reason:Literal['stop']
    usage:dict[str,int]
    model_id:str
