from __future__ import annotations
import os
import dataclasses as dc
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from .validators.settings import validate_settings
from ..utils.exceptions import ValidationError

_BOOL_TRUE = {"1", "true", "yes", "on", "y", "t"}


def _get(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name)
    if v is None:
        if default is None:
            return ""
        return str(default)
    return v


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)).strip())
    except Exception:
        return default


def _get_bool(name: str, default: bool) -> bool:
    v = _get(name, str(int(default))).strip().lower()
    return v in _BOOL_TRUE


def _get_decimal(name: str, default: Decimal) -> Decimal:
    raw = _get(name, str(default))
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Single source of truth for configuration. Only this module reads os.environ."""

    MODE: str = "paper"            # paper | live | backtest
    EXCHANGE: str = "gateio"
    SYMBOL: str = "BTC/USDT"
    FIXED_AMOUNT: Decimal = Decimal("10")  # default monetary/asset unit depending on strategy

    IDEMPOTENCY_TTL_SEC: int = 60
    IDEMPOTENCY_BUCKET_MS: int = 60_000

    DB_PATH: str = "crypto_ai_bot.db"  # SQLite file path
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    METRICS_ENABLED: bool = True
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    API_KEY: str = ""
    API_SECRET: str = ""

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from environment and validate. Fail-fast on errors."""
        obj = cls(
            MODE=_get("MODE", cls.MODE),
            EXCHANGE=_get("EXCHANGE", cls.EXCHANGE),
            SYMBOL=_get("SYMBOL", cls.SYMBOL),
            FIXED_AMOUNT=_get_decimal("FIXED_AMOUNT", cls.FIXED_AMOUNT),
            IDEMPOTENCY_TTL_SEC=_get_int("IDEMPOTENCY_TTL_SEC", cls.IDEMPOTENCY_TTL_SEC),
            IDEMPOTENCY_BUCKET_MS=_get_int("IDEMPOTENCY_BUCKET_MS", cls.IDEMPOTENCY_BUCKET_MS),
            DB_PATH=_get("DB_PATH", cls.DB_PATH),
            SERVER_HOST=_get("SERVER_HOST", cls.SERVER_HOST),
            SERVER_PORT=_get_int("SERVER_PORT", cls.SERVER_PORT),
            METRICS_ENABLED=_get_bool("METRICS_ENABLED", cls.METRICS_ENABLED),
            TELEGRAM_ENABLED=_get_bool("TELEGRAM_ENABLED", cls.TELEGRAM_ENABLED),
            TELEGRAM_BOT_TOKEN=_get("TELEGRAM_BOT_TOKEN", cls.TELEGRAM_BOT_TOKEN),
            TELEGRAM_CHAT_ID=_get("TELEGRAM_CHAT_ID", cls.TELEGRAM_CHAT_ID),
            API_KEY=_get("API_KEY", cls.API_KEY),
            API_SECRET=_get("API_SECRET", cls.API_SECRET),
        )
        errors = validate_settings(obj)
        if errors:
            redacted = [
                e.replace(obj.API_KEY, "***").replace(obj.API_SECRET, "***")
                if obj.API_KEY or obj.API_SECRET else e
                for e in errors
            ]
            raise ValidationError("Invalid Settings: " + "; ".join(redacted))
        return obj

    def migrate_live_keys(
        self,
        live_api_key: str,
        live_api_secret: str,
        fixed_quote: Decimal,
    ) -> "Settings":
        return dc.replace(
            self,
            API_KEY=live_api_key,
            API_SECRET=live_api_secret,
            FIXED_AMOUNT=fixed_quote,
        )

    def as_dict(self) -> dict:
        return {
            "MODE": self.MODE,
            "EXCHANGE": self.EXCHANGE,
            "SYMBOL": self.SYMBOL,
            "FIXED_AMOUNT": str(self.FIXED_AMOUNT),
            "IDEMPOTENCY_TTL_SEC": self.IDEMPOTENCY_TTL_SEC,
            "IDEMPOTENCY_BUCKET_MS": self.IDEMPOTENCY_BUCKET_MS,
            "DB_PATH": self.DB_PATH,
            "SERVER_HOST": self.SERVER_HOST,
            "SERVER_PORT": self.SERVER_PORT,
            "METRICS_ENABLED": self.METRICS_ENABLED,
            "TELEGRAM_ENABLED": self.TELEGRAM_ENABLED,
            "TELEGRAM_BOT_TOKEN": "***" if self.TELEGRAM_BOT_TOKEN else "",
            "TELEGRAM_CHAT_ID": self.TELEGRAM_CHAT_ID,
            "API_KEY": "***" if self.API_KEY else "",
            "API_SECRET": "***" if self.API_SECRET else "",
        }
