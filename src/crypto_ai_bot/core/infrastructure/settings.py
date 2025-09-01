from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from crypto_ai_bot.utils.decimal import dec

def _get(name: str, default: str) -> str:
    return os.getenv(name, default)

def _secret(name: str, default: str = "") -> str:
    # Supports VAR, VAR_FILE, VAR_B64
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
            return base64.b64decode(b64).decode("utf-8").strip()
        except Exception:
            return default
    return default

@dataclass
class Settings:
    # Core
    MODE: str
    EXCHANGE: str
    SYMBOLS: list[str]
    SYMBOL: str  # backward-compat for single-symbol code paths
    DB_PATH: str

    # Event bus
    EVENT_BUS_URL: str

    # HTTP
    HTTP_TIMEOUT_SEC: int

    # Intervals (sec)
    EVALUATE_INTERVAL_SEC: int
    EXITS_INTERVAL_SEC: int
    RECONCILE_INTERVAL_SEC: int
    WATCHDOG_INTERVAL_SEC: int
    SETTLEMENT_INTERVAL_SEC: float

    # Safety / DMS
    DMS_TIMEOUT_MS: int

    # Risk
    RISK_MAX_LOSS_STREAK: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal
    RISK_MAX_DRAWDOWN_PCT: float

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALLOWED_USERS: str
    TELEGRAM_ALERTS_CHAT_ID: str
    TELEGRAM_BOT_COMMANDS_ENABLED: int

    # Broker creds (optional; adapter reads them if needed)
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
        symbols = [s.strip() for s in syms_raw.split(",") if s.strip()]
        sym = symbols[0] if symbols else "BTC/USDT"
        return cls(
            MODE=_get("MODE", "paper"),
            EXCHANGE=_get("EXCHANGE", "gateio"),
            SYMBOLS=symbols,
            SYMBOL=_get("SYMBOL", sym),
            DB_PATH=_get("DB_PATH", "./data/app.db"),
            EVENT_BUS_URL=_get("EVENT_BUS_URL", ""),
            HTTP_TIMEOUT_SEC=int(_get("HTTP_TIMEOUT_SEC", "30")),
            EVALUATE_INTERVAL_SEC=int(_get("EVALUATE_INTERVAL_SEC", "5")),
            EXITS_INTERVAL_SEC=int(_get("EXITS_INTERVAL_SEC", "5")),
            RECONCILE_INTERVAL_SEC=int(_get("RECONCILE_INTERVAL_SEC", "60")),
            WATCHDOG_INTERVAL_SEC=int(_get("WATCHDOG_INTERVAL_SEC", "15")),
            SETTLEMENT_INTERVAL_SEC=float(_get("SETTLEMENT_INTERVAL_SEC", "60")),
            DMS_TIMEOUT_MS=int(_get("DMS_TIMEOUT_MS", "120000")),
            RISK_MAX_LOSS_STREAK=int(_get("RISK_MAX_LOSS_STREAK", "2")),
            RISK_DAILY_LOSS_LIMIT_QUOTE=dec(_get("RISK_DAILY_LOSS_LIMIT_QUOTE", "100")),
            RISK_MAX_DRAWDOWN_PCT=float(_get("RISK_MAX_DRAWDOWN_PCT", "10.0")),
            TELEGRAM_BOT_TOKEN=_secret("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_ALLOWED_USERS=_get("TELEGRAM_ALLOWED_USERS", ""),
            TELEGRAM_ALERTS_CHAT_ID=_get("TELEGRAM_ALERTS_CHAT_ID", ""),
            TELEGRAM_BOT_COMMANDS_ENABLED=int(_get("TELEGRAM_BOT_COMMANDS_ENABLED", "0")),
            API_KEY=_secret("API_KEY", ""),
            API_SECRET=_secret("API_SECRET", ""),
            API_PASSWORD=_secret("API_PASSWORD", ""),
            SANDBOX=int(_get("SANDBOX", "0")),
            POD_NAME=_get("POD_NAME", ""),
            HOSTNAME=_get("HOSTNAME", ""),
        )
