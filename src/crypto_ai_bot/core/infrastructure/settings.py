from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, List

from crypto_ai_bot.core.infrastructure.settings_schema import validate_settings
from crypto_ai_bot.utils.decimal import dec


# --------- helpers ---------
def _get(name: str, default: str) -> str:
    return os.getenv(name, default)

def _read_text_file(path: str) -> str:
    try:
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

def _secret(name: str, default: str = "") -> str:
    """
    Secrets resolution order (first match wins):
      - ${NAME}_FILE : path to text file
      - ${NAME}_B64  : base64-encoded value
      - SECRETS_FILE : JSON file with lowercased keys (e.g., "api_key")
      - ${NAME}      : plain env var
    """
    val_file = os.getenv(f"{name}_FILE")
    if val_file:
        txt = _read_text_file(val_file)
        if txt:
            return txt
    val_b64 = os.getenv(f"{name}_B64")
    if val_b64:
        try:
            return base64.b64decode(val_b64).decode("utf-8").strip()
        except Exception:
            pass
    secrets_path = os.getenv("SECRETS_FILE")
    if secrets_path:
        try:
            data = json.loads(Path(secrets_path).read_text(encoding="utf-8"))
            key = name.lower()
            if data.get(key):
                return str(data[key]).strip()
        except Exception:
            pass
    return os.getenv(name, default)

def _list(name: str, default: str = "") -> List[str]:
    raw = _get(name, default)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts


# --------- settings model ---------
@dataclass
class Settings:
    # mode / exchange / symbols
    MODE: str
    SANDBOX: int
    EXCHANGE: str
    SYMBOL: str
    SYMBOLS: str  # comma-separated list

    # amounts & pricing
    FIXED_AMOUNT: float
    PRICE_FEED: str
    FIXED_PRICE: float

    # storage
    DB_PATH: str
    BACKUP_RETENTION_DAYS: int

    # idempotency
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    # event bus / redis
    EVENT_BUS_URL: str  # "" => in-memory; "redis://..." => RedisEventBus

    # risk & safety (application-level caps)
    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: float
    RISK_MAX_ORDERS_PER_HOUR: int  # kept for backward compatibility
    RISK_DAILY_LOSS_LIMIT_QUOTE: float

    FEE_PCT_ESTIMATE: Decimal
    RISK_MAX_FEE_PCT: Decimal
    RISK_MAX_SLIPPAGE_PCT: Decimal

    # extended risk caps (5m caps etc.)
    RISK_MAX_ORDERS_5M: int
    RISK_MAX_TURNOVER_5M_QUOTE: float
    SAFETY_MAX_ORDERS_PER_DAY: int
    SAFETY_MAX_TURNOVER_QUOTE_PER_DAY: float

    # broker throttling
    BROKER_RATE_RPS: float
    BROKER_RATE_BURST: int

    # orchestrator intervals
    HTTP_TIMEOUT_SEC: int
    TRADER_AUTOSTART: int

    EVAL_ENABLED: int
    EXITS_ENABLED: int
    RECONCILE_ENABLED: int
    WATCHDOG_ENABLED: int
    SETTLEMENT_ENABLED: int

    EVAL_INTERVAL_SEC: int
    EXITS_INTERVAL_SEC: int
    RECONCILE_INTERVAL_SEC: int
    WATCHDOG_INTERVAL_SEC: int
    SETTLEMENT_INTERVAL_SEC: int

    # dead man's switch
    DMS_TIMEOUT_MS: int
    DMS_RECHECKS: int
    DMS_RECHECK_DELAY_SEC: float
    DMS_MAX_IMPACT_PCT: float

    # exits
    EXITS_MODE: str
    EXITS_HARD_STOP_PCT: float
    EXITS_TRAILING_PCT: float
    EXITS_MIN_BASE_TO_EXIT: float

    # Telegram (publisher + commands)
    TELEGRAM_ENABLED: int
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    TELEGRAM_ALERTS_CHAT_ID: str
    TELEGRAM_BOT_COMMANDS_ENABLED: int
    TELEGRAM_ALLOWED_USERS: str  # "123,456"

    # Regime gating (macro regime filter)
    REGIME_ENABLED: int
    REGIME_DXY_URL: str
    REGIME_BTC_DOM_URL: str
    REGIME_FOMC_URL: str
    REGIME_HTTP_TIMEOUT_SEC: float
    REGIME_DXY_LIMIT_PCT: float
    REGIME_BTC_DOM_LIMIT_PCT: float
    REGIME_FOMC_BLOCK_HOURS: int

    # strategy weights (clean defaults; invariant: sum==1.0 ± eps)
    MTF_W_M15: float
    MTF_W_H1: float
    MTF_W_H4: float
    MTF_W_D1: float
    MTF_W_W1: float
    FUSION_W_TECHNICAL: float
    FUSION_W_AI: float

    # api creds / runtime
    API_TOKEN: str
    API_KEY: str
    API_SECRET: str
    POD_NAME: str
    HOSTNAME: str

    # session & correlation
    SESSION_RUN_ID: str
    RISK_ANTI_CORR_GROUPS: str  # e.g. "BTC/USDT|ETH/USDT;XRP/USDT|ADA/USDT"

    @classmethod
    def load(cls) -> "Settings":
        mode = _get("MODE", "paper")
        base, quote = (_get("SYMBOL", "BTC/USDT").split("/") + ["USDT"])[:2]
        db_default = (
            f"./data/trader-{_get('EXCHANGE','gateio')}-{base}{quote}-{mode}"
            f"{'-sandbox' if _get('SANDBOX','0').lower() in ('1','true','yes') else ''}.sqlite3"
        )

        # SAFETY_* aliases -> also populate RISK_* if only SAFETY_* provided
        # (we keep SAFETY_* in the model for backward compatibility)
        safety_per_day = int(_get("SAFETY_MAX_ORDERS_PER_DAY", _get("RISK_MAX_ORDERS_PER_DAY", "0")) or "0")
        safety_turnover = float(_get("SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", "0") or "0")

        s = cls(
            # core
            MODE=mode,
            SANDBOX=int(_get("SANDBOX", "0")),
            EXCHANGE=_get("EXCHANGE", "gateio"),
            SYMBOL=_get("SYMBOL", "BTC/USDT"),
            SYMBOLS=_get("SYMBOLS", ""),

            FIXED_AMOUNT=float(_get("FIXED_AMOUNT", "50")),
            PRICE_FEED=_get("PRICE_FEED", "fixed"),
            FIXED_PRICE=float(_get("FIXED_PRICE", "100")),

            DB_PATH=_get("DB_PATH", db_default),
            BACKUP_RETENTION_DAYS=int(_get("BACKUP_RETENTION_DAYS", "30")),

            IDEMPOTENCY_BUCKET_MS=int(_get("IDEMPOTENCY_BUCKET_MS", "60000")),
            IDEMPOTENCY_TTL_SEC=int(_get("IDEMPOTENCY_TTL_SEC", "3600")),

            EVENT_BUS_URL=_get("EVENT_BUS_URL", ""),  # "" -> in-memory bus, set "redis://..." to enable Redis

            # risk
            RISK_COOLDOWN_SEC=int(_get("RISK_COOLDOWN_SEC", "60")),
            RISK_MAX_SPREAD_PCT=float(_get("RISK_MAX_SPREAD_PCT", "0.30")),  # 0.30% — консервативный дефолт
            RISK_MAX_POSITION_BASE=float(_get("RISK_MAX_POSITION_BASE", "0.02")),
            RISK_MAX_ORDERS_PER_HOUR=int(_get("RISK_MAX_ORDERS_PER_HOUR", "6")),
            RISK_DAILY_LOSS_LIMIT_QUOTE=float(_get("RISK_DAILY_LOSS_LIMIT_QUOTE", "100")),

            FEE_PCT_ESTIMATE=dec(_get("FEE_PCT_ESTIMATE", "0.001")),
            RISK_MAX_FEE_PCT=dec(_get("RISK_MAX_FEE_PCT", "0.001")),
            RISK_MAX_SLIPPAGE_PCT=dec(_get("RISK_MAX_SLIPPAGE_PCT", "0.10")),  # 0.10% дефолт

            # extended risk caps
            RISK_MAX_ORDERS_5M=int(_get("RISK_MAX_ORDERS_5M", "0")),
            RISK_MAX_TURNOVER_5M_QUOTE=float(_get("RISK_MAX_TURNOVER_5M_QUOTE", "0")),
            SAFETY_MAX_ORDERS_PER_DAY=safety_per_day,
            SAFETY_MAX_TURNOVER_QUOTE_PER_DAY=safety_turnover,

            # broker throttle
            BROKER_RATE_RPS=float(_get("BROKER_RATE_RPS", "8.0")),
            BROKER_RATE_BURST=int(_get("BROKER_RATE_BURST", "16")),

            # orchestrator & timeouts
            HTTP_TIMEOUT_SEC=int(_get("HTTP_TIMEOUT_SEC", "30")),
            TRADER_AUTOSTART=int(_get("TRADER_AUTOSTART", "0")),

            EVAL_ENABLED=int(_get("EVAL_ENABLED", "1")),
            EXITS_ENABLED=int(_get("EXITS_ENABLED", "1")),
            RECONCILE_ENABLED=int(_get("RECONCILE_ENABLED", "1")),
            WATCHDOG_ENABLED=int(_get("WATCHDOG_ENABLED", "1")),
            SETTLEMENT_ENABLED=int(_get("SETTLEMENT_ENABLED", "1")),

            EVAL_INTERVAL_SEC=int(_get("EVAL_INTERVAL_SEC", "5")),
            EXITS_INTERVAL_SEC=int(_get("EXITS_INTERVAL_SEC", "5")),
            RECONCILE_INTERVAL_SEC=int(_get("RECONCILE_INTERVAL_SEC", "15")),
            WATCHDOG_INTERVAL_SEC=int(_get("WATCHDOG_INTERVAL_SEC", "10")),
            SETTLEMENT_INTERVAL_SEC=int(_get("SETTLEMENT_INTERVAL_SEC", "7")),

            DMS_TIMEOUT_MS=int(_get("DMS_TIMEOUT_MS", "120000")),
            DMS_RECHECKS=int(_get("DMS_RECHECKS", "2")),
            DMS_RECHECK_DELAY_SEC=float(_get("DMS_RECHECK_DELAY_SEC", "3.0")),
            DMS_MAX_IMPACT_PCT=float(_get("DMS_MAX_IMPACT_PCT", "0.0")),

            EXITS_MODE=_get("EXITS_MODE", "both"),
            EXITS_HARD_STOP_PCT=float(_get("EXITS_HARD_STOP_PCT", "0.05")),
            EXITS_TRAILING_PCT=float(_get("EXITS_TRAILING_PCT", "0.03")),
            EXITS_MIN_BASE_TO_EXIT=float(_get("EXITS_MIN_BASE_TO_EXIT", "0")),

            # Telegram
            TELEGRAM_ENABLED=int(_get("TELEGRAM_ENABLED", "0")),
            TELEGRAM_BOT_TOKEN=_secret("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_CHAT_ID=_get("TELEGRAM_CHAT_ID", ""),
            TELEGRAM_ALERTS_CHAT_ID=_get("TELEGRAM_ALERTS_CHAT_ID", ""),  # optional, can be same as TELEGRAM_CHAT_ID
            TELEGRAM_BOT_COMMANDS_ENABLED=int(_get("TELEGRAM_BOT_COMMANDS_ENABLED", "0")),
            TELEGRAM_ALLOWED_USERS=_get("TELEGRAM_ALLOWED_USERS", ""),

            # Regime gating
            REGIME_ENABLED=int(_get("REGIME_ENABLED", "0")),
            REGIME_DXY_URL=_get("REGIME_DXY_URL", ""),
            REGIME_BTC_DOM_URL=_get("REGIME_BTC_DOM_URL", ""),
            REGIME_FOMC_URL=_get("REGIME_FOMC_URL", ""),
            REGIME_HTTP_TIMEOUT_SEC=float(_get("REGIME_HTTP_TIMEOUT_SEC", "5.0")),
            REGIME_DXY_LIMIT_PCT=float(_get("REGIME_DXY_LIMIT_PCT", "0.35")),
            REGIME_BTC_DOM_LIMIT_PCT=float(_get("REGIME_BTC_DOM_LIMIT_PCT", "0.60")),
            REGIME_FOMC_BLOCK_HOURS=int(_get("REGIME_FOMC_BLOCK_HOURS", "8")),

            # strategy weights — чистые дефолты (инварианты валидируем в schema)
            MTF_W_M15=float(_get("MTF_W_M15", "0.40")),
            MTF_W_H1=float(_get("MTF_W_H1", "0.25")),
            MTF_W_H4=float(_get("MTF_W_H4", "0.20")),
            MTF_W_D1=float(_get("MTF_W_D1", "0.10")),
            MTF_W_W1=float(_get("MTF_W_W1", "0.05")),
            FUSION_W_TECHNICAL=float(_get("FUSION_W_TECHNICAL", "0.65")),
            FUSION_W_AI=float(_get("FUSION_W_AI", "0.35")),

            # creds/runtime
            API_TOKEN=_get("API_TOKEN", ""),
            API_KEY=_secret("API_KEY", ""),
            API_SECRET=_secret("API_SECRET", ""),
            POD_NAME=_get("POD_NAME", ""),
            HOSTNAME=_get("HOSTNAME", ""),

            SESSION_RUN_ID=_get("SESSION_RUN_ID", ""),
            RISK_ANTI_CORR_GROUPS=_get("RISK_ANTI_CORR_GROUPS", ""),
        )

        # validate invariants (raises on invalid)
        validate_settings(s)
        return s
