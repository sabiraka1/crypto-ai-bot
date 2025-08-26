from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _d(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


@dataclass
class Settings:
    # режимы и биржа
    MODE: str = os.getenv("MODE", "paper")              # paper|live
    EXCHANGE: str = os.getenv("EXCHANGE", "gateio")
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    SANDBOX: int = int(os.getenv("SANDBOX", "0"))       # для ccxt (live)
    API_KEY: str = os.getenv("API_KEY", "")
    API_SECRET: str = os.getenv("API_SECRET", "")

    # база
    DB_PATH: str = os.getenv("DB_PATH", "./data/trader.sqlite3")

    # оркестратор — интервалы (сек)
    EVAL_INTERVAL_SEC: float = float(os.getenv("EVAL_INTERVAL_SEC", "1"))
    EXITS_INTERVAL_SEC: float = float(os.getenv("EXITS_INTERVAL_SEC", "2"))
    RECONCILE_INTERVAL_SEC: float = float(os.getenv("RECONCILE_INTERVAL_SEC", "5"))
    WATCHDOG_INTERVAL_SEC: float = float(os.getenv("WATCHDOG_INTERVAL_SEC", "2"))

    # идемпотенси
    IDEMPOTENCY_BUCKET_MS: int = int(os.getenv("IDEMPOTENCY_BUCKET_MS", "60000"))
    IDEMPOTENCY_TTL_SEC: int = int(os.getenv("IDEMPOTENCY_TTL_SEC", "3600"))

    # риск-менеджмент (примерные дефолты)
    RISK_COOLDOWN_SEC: int = int(os.getenv("RISK_COOLDOWN_SEC", "10"))
    RISK_MAX_SPREAD_PCT: float = float(os.getenv("RISK_MAX_SPREAD_PCT", "0.5"))
    RISK_MAX_POSITION_BASE: Decimal = _d("RISK_MAX_POSITION_BASE", "1")
    RISK_MAX_ORDERS_PER_HOUR: int = int(os.getenv("RISK_MAX_ORDERS_PER_HOUR", "30"))
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal = _d("RISK_DAILY_LOSS_LIMIT_QUOTE", "200")

    # торговля
    FIXED_AMOUNT: Decimal = _d("FIXED_AMOUNT", "50")  # USDT сумма на покупку

    # house-keeping / ретеншн
    RETENTION_AUDIT_DAYS: int = int(os.getenv("RETENTION_AUDIT_DAYS", "7"))
    RETENTION_MARKET_DATA_DAYS: int = int(os.getenv("RETENTION_MARKET_DATA_DAYS", "3"))
    RETENTION_IDEMPOTENCY_SEC: int = int(os.getenv("RETENTION_IDEMPOTENCY_SEC", "86400"))
    RETENTION_RECON_TRADES_DAYS: int = int(os.getenv("RETENTION_RECON_TRADES_DAYS", "30"))

    # Decimal precision (общий центр)
    DECIMAL_PREC: int = int(os.getenv("DECIMAL_PREC", "28"))

    @classmethod
    def load(cls) -> "Settings":
        return cls()
