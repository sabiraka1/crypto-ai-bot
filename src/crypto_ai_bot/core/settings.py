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


def _read_secret(name: str, file_name: str) -> str:
    file_path = _env(file_name)
    if file_path:
        try:
            p = Path(file_path)
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return _env(name, "") or ""


def _default_db_path(exchange: str, symbol: str, mode: str, sandbox: bool) -> str:
    pair = symbol.replace("/", "")
    suffix = "-sandbox" if (mode.lower() == "live" and sandbox) else ""
    fname = f"trader-{exchange}-{pair}-{mode.lower()}{suffix}.sqlite3"
    return str(Path("./data") / fname)


@dataclass(frozen=True)
class Settings:
    MODE: str
    SANDBOX: bool
    EXCHANGE: str
    SYMBOL: str

    FIXED_AMOUNT: Decimal

    DB_PATH: str
    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    RISK_COOLDOWN_SEC: int
    RISK_MAX_SPREAD_PCT: float
    RISK_MAX_POSITION_BASE: float
    RISK_MAX_ORDERS_PER_HOUR: int
    RISK_DAILY_LOSS_LIMIT_QUOTE: float

    API_KEY: str
    API_SECRET: str

    PRICE_FEED: str
    FIXED_PRICE: Decimal

    EVAL_INTERVAL_SEC: float
    EXITS_INTERVAL_SEC: float
    RECONCILE_INTERVAL_SEC: float
    WATCHDOG_INTERVAL_SEC: float

    def __post_init__(self):
        # Режим
        m = self.MODE.lower()
        if m not in ("paper", "live"):
            raise ValueError("MODE must be 'paper' or 'live'")
        # Символ
        if "/" not in self.SYMBOL:
            raise ValueError("SYMBOL must be in format BASE/QUOTE, e.g. BTC/USDT")
        # Интервалы
        if self.EVAL_INTERVAL_SEC < 1:
            raise ValueError("EVAL_INTERVAL_SEC must be >= 1")
        if self.EXITS_INTERVAL_SEC <= 0:
            raise ValueError("EXITS_INTERVAL_SEC must be > 0")
        if self.RECONCILE_INTERVAL_SEC <= 0:
            raise ValueError("RECONCILE_INTERVAL_SEC must be > 0")
        if self.WATCHDOG_INTERVAL_SEC <= 0:
            raise ValueError("WATCHDOG_INTERVAL_SEC must be > 0")
        # Live: ключи
        if m == "live" and (not self.API_KEY or not self.API_SECRET):
            raise ValueError("Live mode requires API_KEY and API_SECRET (or *_FILE)")
        # Price feed
        if self.PRICE_FEED not in ("fixed", "live"):
            raise ValueError("PRICE_FEED must be 'fixed' or 'live'")
        # Риски
        if self.RISK_COOLDOWN_SEC < 0:
            raise ValueError("RISK_COOLDOWN_SEC must be >= 0")
        if self.RISK_MAX_SPREAD_PCT < 0:
            raise ValueError("RISK_MAX_SPREAD_PCT must be >= 0")
        if self.RISK_MAX_POSITION_BASE < 0:
            raise ValueError("RISK_MAX_POSITION_BASE must be >= 0")
        if self.RISK_MAX_ORDERS_PER_HOUR < 0:
            raise ValueError("RISK_MAX_ORDERS_PER_HOUR must be >= 0")
        if self.RISK_DAILY_LOSS_LIMIT_QUOTE < 0:
            raise ValueError("RISK_DAILY_LOSS_LIMIT_QUOTE must be >= 0")

    @staticmethod
    def load() -> "Settings":
        mode = _env("MODE", "paper")
        sandbox = _to_bool(_env("SANDBOX", "0"), False)
        exchange = _env("EXCHANGE", "gateio")
        symbol = _env("SYMBOL", "BTC/USDT")

        fixed_amount = Decimal(str(_env("FIXED_AMOUNT", "50")))

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

        api_key = _read_secret("API_KEY", "API_KEY_FILE")
        api_secret = _read_secret("API_SECRET", "API_SECRET_FILE")

        price_feed = (_env("PRICE_FEED", "fixed") or "fixed").lower()
        fixed_price = Decimal(str(_env("FIXED_PRICE", "100")))

        eval_iv = float(_env("EVAL_INTERVAL_SEC", "60.0"))
        exits_iv = float(_env("EXITS_INTERVAL_SEC", "5.0"))
        recon_iv = float(_env("RECONCILE_INTERVAL_SEC", "60.0"))
        wd_iv = float(_env("WATCHDOG_INTERVAL_SEC", "15.0"))

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
            EVAL_INTERVAL_SEC=eval_iv,
            EXITS_INTERVAL_SEC=exits_iv,
            RECONCILE_INTERVAL_SEC=recon_iv,
            WATCHDOG_INTERVAL_SEC=wd_iv,
        )
