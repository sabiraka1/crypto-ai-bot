from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, NonNegativeInt, PositiveFloat, PositiveInt


class TradingConfig(BaseModel):
    SYMBOL: str = Field("BTC/USDT", min_length=3)
    FIXED_AMOUNT: PositiveFloat = 10.0
    RISK_MAX_SLIPPAGE_PCT: float = Field(0.0, ge=0.0, le=5.0)

class SafetyConfig(BaseModel):
    SAFETY_MAX_ORDERS_PER_DAY: NonNegativeInt = 0
    SAFETY_MAX_TURNOVER_QUOTE_PER_DAY: float = 0.0

class BrokerRateConfig(BaseModel):
    BROKER_RATE_RPS: PositiveFloat = 8.0
    BROKER_RATE_BURST: PositiveInt = 16

class AppConfig(BaseModel):
    trading: TradingConfig
    safety: SafetyConfig
    broker: BrokerRateConfig

def validate_settings(settings: Any) -> None:
    data = {
        "trading": {
            "SYMBOL": getattr(settings, "SYMBOL", "BTC/USDT"),
            "FIXED_AMOUNT": float(getattr(settings, "FIXED_AMOUNT", 10.0) or 10.0),
            "RISK_MAX_SLIPPAGE_PCT": float(getattr(settings, "RISK_MAX_SLIPPAGE_PCT", 0.0) or 0.0),
        },
        "safety": {
            "SAFETY_MAX_ORDERS_PER_DAY": int(getattr(settings, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
            "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY": float(getattr(settings, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0.0) or 0.0),
        },
        "broker": {
            "BROKER_RATE_RPS": float(getattr(settings, "BROKER_RATE_RPS", 8.0) or 8.0),
            "BROKER_RATE_BURST": int(getattr(settings, "BROKER_RATE_BURST", 16) or 16),
        },
    }
    AppConfig.model_validate(data)  # бросит ValidationError при проблеме
