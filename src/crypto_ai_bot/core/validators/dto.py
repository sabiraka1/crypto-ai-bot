from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class OrderInputDTO(BaseModel):
    """Валидация входящих параметров ордера."""
    symbol: str = Field(..., min_length=3)
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    amount: float = Field(..., gt=0)
    price: float | None = Field(None, gt=0)

    @field_validator("side", "type", mode="before")
    @classmethod
    def _lowercase(cls, v):
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _limit_price_required(self):
        if self.type == "limit" and self.price is None:
            raise ValueError("price обязателен для limit-ордера")
        return self