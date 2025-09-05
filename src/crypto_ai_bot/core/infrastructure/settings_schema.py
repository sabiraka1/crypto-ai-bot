from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
)


# ---------- Sub-schemas ----------
class TradingConfig(BaseModel):
    SYMBOL: str = Field("BTC/USDT", min_length=3)
    FIXED_AMOUNT: PositiveFloat = 10.0
    RISK_MAX_SLIPPAGE_PCT: float = Field(
        0.10, ge=0.0, le=5.0
    )  # Max slippage 5% protection limit


class SafetyConfig(BaseModel):
    SAFETY_MAX_ORDERS_PER_DAY: NonNegativeInt = 0
    SAFETY_MAX_TURNOVER_QUOTE_PER_DAY: float = Field(0.0, ge=0.0)


class RiskCapsConfig(BaseModel):
    RISK_COOLDOWN_SEC: NonNegativeInt = 60
    RISK_MAX_SPREAD_PCT: float = Field(0.30, ge=0.0, le=5.0)
    RISK_DAILY_LOSS_LIMIT_QUOTE: float = Field(100.0, ge=0.0)
    RISK_MAX_ORDERS_5M: NonNegativeInt = 0
    RISK_MAX_TURNOVER_5M_QUOTE: float = Field(0.0, ge=0.0)


class BrokerRateConfig(BaseModel):
    BROKER_RATE_RPS: PositiveFloat = 8.0
    BROKER_RATE_BURST: PositiveInt = 16


class OrchestratorIntervals(BaseModel):
    EVAL_INTERVAL_SEC: PositiveInt = 5
    EXITS_INTERVAL_SEC: PositiveInt = 5
    RECONCILE_INTERVAL_SEC: PositiveInt = 15
    WATCHDOG_INTERVAL_SEC: PositiveInt = 10
    SETTLEMENT_INTERVAL_SEC: PositiveInt = 7


class MTFWeights(BaseModel):
    MTF_W_M15: float = Field(0.40, ge=0.0, le=1.0)
    MTF_W_H1: float = Field(0.25, ge=0.0, le=1.0)
    MTF_W_H4: float = Field(0.20, ge=0.0, le=1.0)
    MTF_W_D1: float = Field(0.10, ge=0.0, le=1.0)
    MTF_W_W1: float = Field(0.05, ge=0.0, le=1.0)

    @field_validator("MTF_W_W1")
    @classmethod
    def _sum_to_one(cls, v: float, values: Any) -> float:
        s = (
            float(values.get("MTF_W_M15", 0))
            + float(values.get("MTF_W_H1", 0))
            + float(values.get("MTF_W_H4", 0))
            + float(values.get("MTF_W_D1", 0))
            + float(v)
        )
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"MTF weights must sum to 1.0, got {s:.6f}")
        return v


class FusionWeights(BaseModel):
    FUSION_W_TECHNICAL: float = Field(0.65, ge=0.0, le=1.0)
    FUSION_W_AI: float = Field(0.35, ge=0.0, le=1.0)

    @field_validator("FUSION_W_AI")
    @classmethod
    def _sum_to_one(cls, v: float, values: Any) -> float:
        s = float(values.get("FUSION_W_TECHNICAL", 0)) + float(v)
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"Fusion weights must sum to 1.0, got {s:.6f}")
        return v


class TelegramConfig(BaseModel):
    TELEGRAM_ENABLED: int = 0
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_BOT_COMMANDS_ENABLED: int = 0
    TELEGRAM_ALLOWED_USERS: str = ""


class RegimeConfig(BaseModel):
    REGIME_ENABLED: int = 0
    REGIME_DXY_LIMIT_PCT: float = Field(0.35, ge=0.0, le=10.0)
    REGIME_BTC_DOM_LIMIT_PCT: float = Field(0.60, ge=0.0, le=10.0)
    REGIME_FOMC_BLOCK_HOURS: PositiveInt = 8


# ---------- Aggregate ----------
class AppConfig(BaseModel):
    trading: TradingConfig
    safety: SafetyConfig
    risk: RiskCapsConfig
    broker: BrokerRateConfig
    loops: OrchestratorIntervals
    mtf: MTFWeights
    fusion: FusionWeights
    telegram: TelegramConfig
    regime: RegimeConfig


def validate_settings(settings: Any) -> None:
    """
    Collect values from Settings (dataclass) and validate invariants.
    Raises pydantic.ValidationError on invalid config.
    """
    data = {
        "trading": {
            "SYMBOL": getattr(settings, "SYMBOL", "BTC/USDT"),
            "FIXED_AMOUNT": float(getattr(settings, "FIXED_AMOUNT", 10.0) or 10.0),
            "RISK_MAX_SLIPPAGE_PCT": float(getattr(settings, "RISK_MAX_SLIPPAGE_PCT", 0.10) or 0.10),
        },
        "safety": {
            "SAFETY_MAX_ORDERS_PER_DAY": int(getattr(settings, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
            "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY": float(
                getattr(settings, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0.0) or 0.0
            ),
        },
        "risk": {
            "RISK_COOLDOWN_SEC": int(getattr(settings, "RISK_COOLDOWN_SEC", 60) or 60),
            "RISK_MAX_SPREAD_PCT": float(getattr(settings, "RISK_MAX_SPREAD_PCT", 0.30) or 0.30),
            "RISK_DAILY_LOSS_LIMIT_QUOTE": float(
                getattr(settings, "RISK_DAILY_LOSS_LIMIT_QUOTE", 100.0) or 100.0
            ),
            "RISK_MAX_ORDERS_5M": int(getattr(settings, "RISK_MAX_ORDERS_5M", 0) or 0),
            "RISK_MAX_TURNOVER_5M_QUOTE": float(getattr(settings, "RISK_MAX_TURNOVER_5M_QUOTE", 0.0) or 0.0),
        },
        "broker": {
            "BROKER_RATE_RPS": float(getattr(settings, "BROKER_RATE_RPS", 8.0) or 8.0),
            "BROKER_RATE_BURST": int(getattr(settings, "BROKER_RATE_BURST", 16) or 16),
        },
        "loops": {
            "EVAL_INTERVAL_SEC": int(getattr(settings, "EVAL_INTERVAL_SEC", 5) or 5),
            "EXITS_INTERVAL_SEC": int(getattr(settings, "EXITS_INTERVAL_SEC", 5) or 5),
            "RECONCILE_INTERVAL_SEC": int(getattr(settings, "RECONCILE_INTERVAL_SEC", 15) or 15),
            "WATCHDOG_INTERVAL_SEC": int(getattr(settings, "WATCHDOG_INTERVAL_SEC", 10) or 10),
            "SETTLEMENT_INTERVAL_SEC": int(getattr(settings, "SETTLEMENT_INTERVAL_SEC", 7) or 7),
        },
        "mtf": {
            "MTF_W_M15": float(getattr(settings, "MTF_W_M15", 0.40) or 0.40),
            "MTF_W_H1": float(getattr(settings, "MTF_W_H1", 0.25) or 0.25),
            "MTF_W_H4": float(getattr(settings, "MTF_W_H4", 0.20) or 0.20),
            "MTF_W_D1": float(getattr(settings, "MTF_W_D1", 0.10) or 0.10),
            "MTF_W_W1": float(getattr(settings, "MTF_W_W1", 0.05) or 0.05),
        },
        "fusion": {
            "FUSION_W_TECHNICAL": float(getattr(settings, "FUSION_W_TECHNICAL", 0.65) or 0.65),
            "FUSION_W_AI": float(getattr(settings, "FUSION_W_AI", 0.35) or 0.35),
        },
        "telegram": {
            "TELEGRAM_ENABLED": int(getattr(settings, "TELEGRAM_ENABLED", 0) or 0),
            "TELEGRAM_BOT_TOKEN": str(getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""),
            "TELEGRAM_CHAT_ID": str(getattr(settings, "TELEGRAM_CHAT_ID", "") or ""),
            "TELEGRAM_BOT_COMMANDS_ENABLED": int(getattr(settings, "TELEGRAM_BOT_COMMANDS_ENABLED", 0) or 0),
            "TELEGRAM_ALLOWED_USERS": str(getattr(settings, "TELEGRAM_ALLOWED_USERS", "") or ""),
        },
        "regime": {
            "REGIME_ENABLED": int(getattr(settings, "REGIME_ENABLED", 0) or 0),
            "REGIME_DXY_LIMIT_PCT": float(getattr(settings, "REGIME_DXY_LIMIT_PCT", 0.35) or 0.35),
            "REGIME_BTC_DOM_LIMIT_PCT": float(getattr(settings, "REGIME_BTC_DOM_LIMIT_PCT", 0.60) or 0.60),
            "REGIME_FOMC_BLOCK_HOURS": int(getattr(settings, "REGIME_FOMC_BLOCK_HOURS", 8) or 8),
        },
    }
    AppConfig.model_validate(data)  # raises on invalid
