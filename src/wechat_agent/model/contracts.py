"""Verified capabilities are distinct from values declared in a probe config."""

from pydantic import AwareDatetime, BaseModel, Field, StrictBool, model_validator


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
