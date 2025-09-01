from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from crypto_ai_bot.utils.decimal import dec


def _get(name: str, default: str) -> str:
    return os.getenv(name, default)


def _secret(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val is not None:
        return val
    path = os.getenv(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except Exception:
            return default
    b64 = os.getenv(f"{name}_B64")
    if b64:
        try:
            import base64 as _b64
            return _b64.b64decode(b64).decode("utf-8").strip()
        except Exception:
            return default
    return default


@dataclass
class Settings:
    # Core
    MODE: str
    EXCHANGE: str
    SYMBOLS: list[str] | str  # tests sometimes pass ""
    SYMBOL: str
    DB_PATH: str

    # Backups / migrations
    BACKUP_RETENTION_DAYS: int

    # Idempotency
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    # Event bus
    EVENT_BUS_URL: str

    # HTTP
    HTTP_TIMEOUT_SEC: int

    # Intervals (sec) — allow floats for fast tests
    EVAL_INTERVAL_SEC: float  # alias used by tests
    EVALUATE_INTERVAL_SEC: float
    EXITS_INTERVAL_SEC: float
    RECONCILE_INTERVAL_SEC: float
    WATCHDOG_INTERVAL_SEC: float
    SETTLEMENT_INTERVAL_SEC: float

    # Safety / DMS
    DMS_TIMEOUT_MS: int

    # Risk core
    RISK_MAX_LOSS_STREAK: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal
    RISK_MAX_DRAWDOWN_PCT: float

    # Strategy / trading extras
    FIXED_AMOUNT: float
    PRICE_FEED: str
    FIXED_PRICE: float
    FEE_PCT_ESTIMATE: Decimal
    RISK_MAX_FEE_PCT: Decimal
    RISK_MAX_SLIPPAGE_PCT: Decimal
    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: float
    RISK_MAX_ORDERS_PER_HOUR: int
    TRADER_AUTOSTART: int

    # Exits config
    EXITS_ENABLED: int
    EXITS_MODE: str
    EXITS_HARD_STOP_PCT: float
    EXITS_TRAILING_PCT: float
    EXITS_MIN_BASE_TO_EXIT: float

    # Telemetry / Telegram
    TELEGRAM_ENABLED: int
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALLOWED_USERS: str
    TELEGRAM_ALERTS_CHAT_ID: str
    TELEGRAM_BOT_COMMANDS_ENABLED: int
    TELEGRAM_CHAT_ID: str

    # Tokens / API
    API_TOKEN: str
    API_KEY: str
    API_SECRET: str
    API_PASSWORD: str
    SANDBOX: int

    # Misc
    POD_NAME: str
    HOSTNAME: str

    @classmethod
    def load(cls) -> "Settings":
        syms_raw = _get("SYMBOLS", _get("SYMBOL", "BTC/USDT"))
        # allow both list (via env "A,B") and single symbol
        if "," in syms_raw:
            symbols_list = [s.strip() for s in syms_raw.split(",") if s.strip()]
        else:
            symbols_list = [syms_raw.strip()] if syms_raw else []
        sym = symbols_list[0] if symbols_list else "BTC/USDT"
        eval_interval = float(_get("EVAL_INTERVAL_SEC", _get("EVALUATE_INTERVAL_SEC", "5")))
        return cls(
            MODE=_get("MODE", "paper"),
            EXCHANGE=_get("EXCHANGE", "gateio"),
            SYMBOLS=symbols_list or "",  # tests sometimes assign ""
            SYMBOL=_get("SYMBOL", sym),
            DB_PATH=_get("DB_PATH", ":memory:"),
            BACKUP_RETENTION_DAYS=int(_get("BACKUP_RETENTION_DAYS", "30")),
            IDEMPOTENCY_BUCKET_MS=int(_get("IDEMPOTENCY_BUCKET_MS", "60000")),
            IDEMPOTENCY_TTL_SEC=int(_get("IDEMPOTENCY_TTL_SEC", "3600")),
            EVENT_BUS_URL=_get("EVENT_BUS_URL", ""),
            HTTP_TIMEOUT_SEC=int(_get("HTTP_TIMEOUT_SEC", "30")),
            EVAL_INTERVAL_SEC=eval_interval,
            EVALUATE_INTERVAL_SEC=eval_interval,
            EXITS_INTERVAL_SEC=float(_get("EXITS_INTERVAL_SEC", "5")),
            RECONCILE_INTERVAL_SEC=float(_get("RECONCILE_INTERVAL_SEC", "60")),
            WATCHDOG_INTERVAL_SEC=float(_get("WATCHDOG_INTERVAL_SEC", "15")),
            SETTLEMENT_INTERVAL_SEC=float(_get("SETTLEMENT_INTERVAL_SEC", "60")),
            DMS_TIMEOUT_MS=int(_get("DMS_TIMEOUT_MS", "120000")),
            RISK_MAX_LOSS_STREAK=int(_get("RISK_MAX_LOSS_STREAK", "2")),
            RISK_DAILY_LOSS_LIMIT_QUOTE=dec(_get("RISK_DAILY_LOSS_LIMIT_QUOTE", "100")),
            RISK_MAX_DRAWDOWN_PCT=float(_get("RISK_MAX_DRAWDOWN_PCT", "10.0")),
            FIXED_AMOUNT=float(_get("FIXED_AMOUNT", "50")),
            PRICE_FEED=_get("PRICE_FEED", "fixed"),
            FIXED_PRICE=float(_get("FIXED_PRICE", "100")),
            FEE_PCT_ESTIMATE=dec(_get("FEE_PCT_ESTIMATE", "0.001")),
            RISK_MAX_FEE_PCT=dec(_get("RISK_MAX_FEE_PCT", "0.001")),
            RISK_MAX_SLIPPAGE_PCT=dec(_get("RISK_MAX_SLIPPAGE_PCT", "0.001")),
            RISK_COOLDOWN_SEC=int(_get("RISK_COOLDOWN_SEC", "60")),
            RISK_MAX_SPREAD_PCT=float(_get("RISK_MAX_SPREAD_PCT", "0.3")),
            RISK_MAX_POSITION_BASE=float(_get("RISK_MAX_POSITION_BASE", "0.02")),
            RISK_MAX_ORDERS_PER_HOUR=int(_get("RISK_MAX_ORDERS_PER_HOUR", "6")),
            TRADER_AUTOSTART=int(_get("TRADER_AUTOSTART", "0")),
            EXITS_ENABLED=int(_get("EXITS_ENABLED", "1")),
            EXITS_MODE=_get("EXITS_MODE", "both"),
            EXITS_HARD_STOP_PCT=float(_get("EXITS_HARD_STOP_PCT", "0.05")),
            EXITS_TRAILING_PCT=float(_get("EXITS_TRAILING_PCT", "0.03")),
            EXITS_MIN_BASE_TO_EXIT=float(_get("EXITS_MIN_BASE_TO_EXIT", "0.0")),
            TELEGRAM_ENABLED=int(_get("TELEGRAM_ENABLED", "0")),
            TELEGRAM_BOT_TOKEN=_secret("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_ALLOWED_USERS=_get("TELEGRAM_ALLOWED_USERS", ""),
            TELEGRAM_ALERTS_CHAT_ID=_get("TELEGRAM_ALERTS_CHAT_ID", ""),
            TELEGRAM_BOT_COMMANDS_ENABLED=int(_get("TELEGRAM_BOT_COMMANDS_ENABLED", "0")),
            TELEGRAM_CHAT_ID=_get("TELEGRAM_CHAT_ID", ""),
            API_TOKEN=_secret("API_TOKEN", ""),
            API_KEY=_secret("API_KEY", ""),
            API_SECRET=_secret("API_SECRET", ""),
            API_PASSWORD=_secret("API_PASSWORD", ""),
            SANDBOX=int(_get("SANDBOX", "0")),
            POD_NAME=_get("POD_NAME", ""),
            HOSTNAME=_get("HOSTNAME", ""),
        )
