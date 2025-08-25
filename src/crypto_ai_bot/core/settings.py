from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from .validators.settings import validate_settings

def _getenv_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)

def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _getenv_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

def _getenv_dec(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, default))
    except Exception:
        return Decimal(default)

@dataclass
class Settings:
    MODE: str
    EXCHANGE: str
    SYMBOL: str
    API_KEY: str
    API_SECRET: str
    SANDBOX: bool

    FIXED_AMOUNT: Decimal
    DB_PATH: str
    SERVER_PORT: int

    # идемпотентность
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    # интервалы оркестратора (по спека-дефолтам)
    EVAL_INTERVAL_SEC: float
    EXITS_INTERVAL_SEC: float
    RECONCILE_INTERVAL_SEC: float
    WATCHDOG_INTERVAL_SEC: float

    # risk (без изменений)
    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: Decimal
    RISK_MAX_ORDERS_PER_HOUR: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal

    # Telegram (опционально)
    TELEGRAM_ENABLED: bool
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    @staticmethod
    def load() -> "Settings":
        return Settings(
            MODE=_getenv_str("MODE", "paper"),
            EXCHANGE=_getenv_str("EXCHANGE", "gateio"),
            SYMBOL=_getenv_str("SYMBOL", "BTC/USDT"),
            API_KEY=_getenv_str("API_KEY", ""),
            API_SECRET=_getenv_str("API_SECRET", ""),
            SANDBOX=_getenv_bool("SANDBOX", False),

            FIXED_AMOUNT=_getenv_dec("FIXED_AMOUNT", "10"),
            DB_PATH=_getenv_str("DB_PATH", "./db.sqlite"),
            SERVER_PORT=_getenv_int("SERVER_PORT", 8000),

            IDEMPOTENCY_BUCKET_MS=_getenv_int("IDEMPOTENCY_BUCKET_MS", 60000),
            IDEMPOTENCY_TTL_SEC=_getenv_int("IDEMPOTENCY_TTL_SEC", 120),

            # дефолты по твоей спецификации (не жёстко зашитые, а из ENV)
            EVAL_INTERVAL_SEC=float(os.getenv("EVAL_INTERVAL_SEC", "60")),
            EXITS_INTERVAL_SEC=float(os.getenv("EXITS_INTERVAL_SEC", "5")),
            RECONCILE_INTERVAL_SEC=float(os.getenv("RECONCILE_INTERVAL_SEC", "60")),
            WATCHDOG_INTERVAL_SEC=float(os.getenv("WATCHDOG_INTERVAL_SEC", "15")),

            RISK_COOLDOWN_SEC=_getenv_int("RISK_COOLDOWN_SEC", 60),
            RISK_MAX_SPREAD_PCT=float(os.getenv("RISK_MAX_SPREAD_PCT", "0.002")),  # 0.2%
            RISK_MAX_POSITION_BASE=_getenv_dec("RISK_MAX_POSITION_BASE", "10"),
            RISK_MAX_ORDERS_PER_HOUR=_getenv_int("RISK_MAX_ORDERS_PER_HOUR", 12),
            RISK_DAILY_LOSS_LIMIT_QUOTE=_getenv_dec("RISK_DAILY_LOSS_LIMIT_QUOTE", "100"),

            TELEGRAM_ENABLED=_getenv_bool("TELEGRAM_ENABLED", False),
            TELEGRAM_BOT_TOKEN=_getenv_str("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_CHAT_ID=_getenv_str("TELEGRAM_CHAT_ID", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    def validate(self) -> None:
        errors = validate_settings(self)
        if errors:
            raise ValueError("Invalid settings: " + "; ".join(errors))
