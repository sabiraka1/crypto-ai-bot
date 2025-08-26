from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if (v is not None and v != "") else default


def _to_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _default_db_path(exchange: str, symbol: str, mode: str, sandbox: bool) -> str:
    # символ без слеша: BTCUSDT
    pair = symbol.replace("/", "")
    suffix = "-sandbox" if (mode.lower() == "live" and sandbox) else ""
    fname = f"trader-{exchange}-{pair}-{mode.lower()}{suffix}.sqlite3"
    return str(Path("./data") / fname)


@dataclass(frozen=True)
class Settings:
    # базовые
    MODE: str
    SANDBOX: bool
    EXCHANGE: str
    SYMBOL: str

    # торговые
    FIXED_AMOUNT: Decimal

    # БД и идемпотентность
    DB_PATH: str
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    # риск-лимиты
    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: float
    RISK_MAX_ORDERS_PER_HOUR: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: float

    # ключи (только для live)
    API_KEY: str
    API_SECRET: str

    # paper-фид цены: fixed|live
    PRICE_FEED: str
    FIXED_PRICE: Decimal

    @staticmethod
    def load() -> "Settings":
        mode = _env("MODE", "paper")
        sandbox = _to_bool(_env("SANDBOX", "0"), False)
        exchange = _env("EXCHANGE", "gateio")
        symbol = _env("SYMBOL", "BTC/USDT")

        fixed_amount = Decimal(str(_env("FIXED_AMOUNT", "50")))

        # DB_PATH: если явно не задан, генерируем по окружению (изоляция сред)
        db_path = _env("DB_PATH")
        if not db_path:
            db_path = _default_db_path(exchange, symbol, mode, sandbox)

        idem_bucket = int(_env("IDEMPOTENCY_BUCKET_MS", "60000"))
        idem_ttl = int(_env("IDEMPOTENCY_TTL_SEC", "3600"))

        risk_cooldown = int(_env("RISK_COOLDOWN_SEC", "60"))
        risk_spread = float(_env("RISK_MAX_SPREAD_PCT", "0.3"))
        risk_pos = float(_env("RISK_MAX_POSITION_BASE", "0.02"))
        risk_rate = int(_env("RISK_MAX_ORDERS_PER_HOUR", "6"))
        risk_daily_loss = float(_env("RISK_DAILY_LOSS_LIMIT_QUOTE", "100"))

        api_key = _env("API_KEY", "") or ""
        api_secret = _env("API_SECRET", "") or ""

        price_feed = (_env("PRICE_FEED", "fixed") or "fixed").lower()  # fixed | live
        fixed_price = Decimal(str(_env("FIXED_PRICE", "100")))

        return Settings(
            MODE=mode,
            SANDBOX=sandbox,
            EXCHANGE=exchange,
            SYMBOL=symbol,
            FIXED_AMOUNT=fixed_amount,
            DB_PATH=db_path,
            IDEMPOTENCY_BUCKET_MS=idem_bucket,
            IDEMPOTENCY_TTL_SEC=idem_ttl,
            RISK_COOLDOWN_SEC=risk_cooldown,
            RISK_MAX_SPREAD_PCT=risk_spread,
            RISK_MAX_POSITION_BASE=risk_pos,
            RISK_MAX_ORDERS_PER_HOUR=risk_rate,
            RISK_DAILY_LOSS_LIMIT_QUOTE=risk_daily_loss,
            API_KEY=api_key,
            API_SECRET=api_secret,
            PRICE_FEED=price_feed,
            FIXED_PRICE=fixed_price,
        )
