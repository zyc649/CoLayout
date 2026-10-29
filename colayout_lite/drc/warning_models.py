"""Persisted user preferences for advisory design checks."""

from math import isfinite
from typing import Literal
from pydantic import Field, model_validator
from ..model import Record


class Direction(Record):
    preferred: Literal['horizontal', 'vertical']
    reverse_limit_um: float = 9.8
    enabled: bool = True

    @model_validator(mode='after')
    def valid(self):
        if not isfinite(self.reverse_limit_um) or self.reverse_limit_um <= 0:
            raise ValueError('Direction warning limit must be positive and finite')
        return self


class DesignWarnings(Record):
    directions: dict[str, Direction] = Field(default_factory=dict)
    via_enabled: bool = True
    minimum_cuts: int = Field(default=2, ge=1, le=10000)

    @model_validator(mode='before')
    @classmethod
    def drop_retired_supply_settings(cls, value):
        # Read existing process files without retaining the removed feature.
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in ('supply_enabled', 'supply_nets')}
        return value
