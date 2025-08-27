from __future__ import annotations

import base64, json, os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from crypto_ai_bot.utils.decimal import dec

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
            if key in data and data[key]:
                return str(data[key]).strip()
        except Exception:
            pass
    return os.getenv(name, default)

@dataclass
class Settings:
    MODE: str
    SANDBOX: int

    EXCHANGE: str
    SYMBOL: str
    SYMBOLS: str

    FIXED_AMOUNT: float
    PRICE_FEED: str
    FIXED_PRICE: float

    DB_PATH: str
    BACKUP_RETENTION_DAYS: int
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: float
    RISK_MAX_ORDERS_PER_HOUR: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: float

    FEE_PCT_ESTIMATE: Decimal
    RISK_MAX_FEE_PCT: Decimal
    RISK_MAX_SLIPPAGE_PCT: Decimal

    HTTP_TIMEOUT_SEC: int
    TRADER_AUTOSTART: int

    EVAL_INTERVAL_SEC: int
    EXITS_INTERVAL_SEC: int
    RECONCILE_INTERVAL_SEC: int
    WATCHDOG_INTERVAL_SEC: int
    DMS_TIMEOUT_MS: int

    EXITS_ENABLED: int
    EXITS_MODE: str
    EXITS_HARD_STOP_PCT: float
    EXITS_TRAILING_PCT: float
    EXITS_MIN_BASE_TO_EXIT: float

    API_TOKEN: str
    API_KEY: str
    API_SECRET: str

    POD_NAME: str
    HOSTNAME: str

    @classmethod
    def load(cls) -> "Settings":
        mode = _get("MODE", "paper")
        base, quote = (_get("SYMBOL", "BTC/USDT").split("/") + ["USDT"])[:2]
        db_default = f"./data/trader-{_get('EXCHANGE','gateio')}-{base}{quote}-{mode}{'-sandbox' if _get('SANDBOX','0') in ('1','true','yes') else ''}.sqlite3"
        return cls(
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
            RISK_COOLDOWN_SEC=int(_get("RISK_COOLDOWN_SEC", "60")),
            RISK_MAX_SPREAD_PCT=float(_get("RISK_MAX_SPREAD_PCT", "0.3")),
            RISK_MAX_POSITION_BASE=float(_get("RISK_MAX_POSITION_BASE", "0.02")),
            RISK_MAX_ORDERS_PER_HOUR=int(_get("RISK_MAX_ORDERS_PER_HOUR", "6")),
            RISK_DAILY_LOSS_LIMIT_QUOTE=float(_get("RISK_DAILY_LOSS_LIMIT_QUOTE", "100")),
            FEE_PCT_ESTIMATE=dec(_get("FEE_PCT_ESTIMATE", "0.001")),
            RISK_MAX_FEE_PCT=dec(_get("RISK_MAX_FEE_PCT", "0.001")),
            RISK_MAX_SLIPPAGE_PCT=dec(_get("RISK_MAX_SLIPPAGE_PCT", "0.001")),
            HTTP_TIMEOUT_SEC=int(_get("HTTP_TIMEOUT_SEC", "30")),
            TRADER_AUTOSTART=int(_get("TRADER_AUTOSTART", "0")),
            EVAL_INTERVAL_SEC=int(_get("EVAL_INTERVAL_SEC", "60")),
            EXITS_INTERVAL_SEC=int(_get("EXITS_INTERVAL_SEC", "5")),
            RECONCILE_INTERVAL_SEC=int(_get("RECONCILE_INTERVAL_SEC", "60")),
            WATCHDOG_INTERVAL_SEC=int(_get("WATCHDOG_INTERVAL_SEC", "15")),
            DMS_TIMEOUT_MS=int(_get("DMS_TIMEOUT_MS", "120000")),
            EXITS_ENABLED=int(_get("EXITS_ENABLED", "1")),
            EXITS_MODE=_get("EXITS_MODE", "both"),
            EXITS_HARD_STOP_PCT=float(_get("EXITS_HARD_STOP_PCT", "0.05")),
            EXITS_TRAILING_PCT=float(_get("EXITS_TRAILING_PCT", "0.03")),
            EXITS_MIN_BASE_TO_EXIT=float(_get("EXITS_MIN_BASE_TO_EXIT", "0")),
            API_TOKEN=_get("API_TOKEN", ""),
            API_KEY=_secret("API_KEY", ""),
            API_SECRET=_secret("API_SECRET", ""),
            POD_NAME=_get("POD_NAME", ""),
            HOSTNAME=_get("HOSTNAME", ""),
        )
