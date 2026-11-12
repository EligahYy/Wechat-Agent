"""Pinned identity extension fields; never use decorated titles as person names."""
from typing import Literal
from pydantic import BaseModel, model_validator


class WireName(BaseModel):
    value: str | None
    state: Literal['known', 'empty', 'unreadable']

    @model_validator(mode='after')
    def coherent_value(self):
        if self.state == 'known' and (not self.value or not self.value.strip()):
            raise ValueError('known_name_requires_value')
        if self.state != 'known' and self.value is not None:
            raise ValueError('non_value_state_requires_null')
        return self
