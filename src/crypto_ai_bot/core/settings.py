from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(str(v)) if v is not None else default
    except Exception:
        return default


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    try:
        return float(str(v)) if v is not None else default
    except Exception:
        return default


def _str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return str(v) if v is not None else default


def _dec(name: str, default: str | float) -> Decimal:
    v = os.getenv(name)
    try:
        return Decimal(str(v)) if v is not None else Decimal(str(default))
    except Exception:
        return Decimal(str(default))


@dataclass
class Settings:
    # режимы
    MODE: str = _str("MODE", "paper")  # paper|live
    EXCHANGE: str = _str("EXCHANGE", "gateio")
    SYMBOL: str = _str("SYMBOL", "BTC/USDT")

    # API
    API_KEY: str = _str("API_KEY", "")
    API_SECRET: str = _str("API_SECRET", "")
    SANDBOX: bool = _bool("SANDBOX", False)

    # торговые параметры
    FIXED_AMOUNT: float = _float("FIXED_AMOUNT", 100.0)

    # интервалы оркестратора
    EVAL_INTERVAL_SEC: float = _float("EVAL_INTERVAL_SEC", 60)
    EXITS_INTERVAL_SEC: float = _float("EXITS_INTERVAL_SEC", 5)
    RECONCILE_INTERVAL_SEC: float = _float("RECONCILE_INTERVAL_SEC", 60)
    WATCHDOG_INTERVAL_SEC: float = _float("WATCHDOG_INTERVAL_SEC", 15)

    # идемпотентность
    IDEMPOTENCY_BUCKET_MS: int = _int("IDEMPOTENCY_BUCKET_MS", 60_000)
    IDEMPOTENCY_TTL_SEC: int = _int("IDEMPOTENCY_TTL_SEC", 600)

    # БД
    DB_PATH: str = _str("DB_PATH", "./data/crypto_ai_bot.sqlite3")

    # paper broker
    PAPER_INITIAL_BALANCE_USDT: Decimal = _dec("PAPER_INITIAL_BALANCE_USDT", "10000")
    PAPER_INITIAL_BALANCE_BASE: Decimal = _dec("PAPER_INITIAL_BALANCE_BASE", "0")
    PAPER_FEE_PCT: Decimal = _dec("PAPER_FEE_PCT", "0.001")
    PAPER_PRICE: Decimal = _dec("PAPER_PRICE", "100.0")

    # risk manager (существующие поля — оставляем)
    RISK_COOLDOWN_SEC: int = _int("RISK_COOLDOWN_SEC", 10)
    RISK_MAX_SPREAD_PCT: float = _float("RISK_MAX_SPREAD_PCT", 0.002)
    RISK_MAX_POSITION_BASE: Decimal = _dec("RISK_MAX_POSITION_BASE", "1.0")
    RISK_MAX_ORDERS_PER_HOUR: int = _int("RISK_MAX_ORDERS_PER_HOUR", 30)
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal = _dec("RISK_DAILY_LOSS_LIMIT_QUOTE", "1000")

    # Protective Exits
    EXITS_ENABLED: bool = _bool("EXITS_ENABLED", True)
    EXITS_MODE: str = _str("EXITS_MODE", "both")  # hard|trailing|both
    EXITS_HARD_STOP_PCT: float = _float("EXITS_HARD_STOP_PCT", 0.05)
    EXITS_TRAILING_PCT: float = _float("EXITS_TRAILING_PCT", 0.03)
    EXITS_MIN_BASE_TO_EXIT: Decimal = _dec("EXITS_MIN_BASE_TO_EXIT", "0.0")

    # Circuit Breaker (для CCXT)
    CB_ENABLED: bool = _bool("CB_ENABLED", True)
    CB_THRESHOLD: int = _int("CB_THRESHOLD", 5)
    CB_WINDOW_SEC: int = _int("CB_WINDOW_SEC", 30)
    CB_COOLDOWN_SEC: int = _int("CB_COOLDOWN_SEC", 60)

    # иные настройки — по мере необходимости

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        # Базовые проверки (fail‑fast по минимуму)
        if s.MODE.lower() == "live" and not s.API_KEY:
            raise RuntimeError("CONFIG: API_KEY is required in live mode")
        if s.IDEMPOTENCY_BUCKET_MS <= 0:
            raise RuntimeError("CONFIG: IDEMPOTENCY_BUCKET_MS must be > 0")
        if s.FIXED_AMOUNT <= 0:
            raise RuntimeError("CONFIG: FIXED_AMOUNT must be > 0")
        return s