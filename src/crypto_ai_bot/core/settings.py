from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from .validators.settings import validate_settings
from ..utils.exceptions import ValidationError  # ✅ берём общий класс

def _getenv_str(name: str, default: str) -> str:
    v = os.environ.get(name, default)
    return v if isinstance(v, str) else str(v)

def _getenv_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v == "":
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)

def _getenv_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v == "":
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)

def _getenv_decimal(name: str, default: Optional[Decimal]) -> Optional[Decimal]:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return Decimal(str(v))
    except (InvalidOperation, Exception):
        return default

@dataclass
class Settings:
    # --- базовые ---
    MODE: str = "paper"                  # paper | live
    EXCHANGE: str = "gateio"
    SYMBOL: str = "BTC/USDT"
    API_KEY: str = ""
    API_SECRET: str = ""
    FIXED_AMOUNT: Decimal = Decimal("10")            # сумма для BUY в QUOTE
    IDEMPOTENCY_BUCKET_MS: int = 60_000              # окно бакета
    IDEMPOTENCY_TTL_SEC: int = 60                    # TTL ключей
    DB_PATH: str = ":memory:"                        # sqlite путь для paper/тестов
    SERVER_PORT: int = 8000                          # 1..65535

    # --- риск-гардрейлы (из ENV) ---
    RISK_COOLDOWN_SEC: int = 30                      # 0 = выкл
    RISK_MAX_SPREAD_PCT: float = 0.3                 # 0 = выкл
    RISK_MAX_POSITION_BASE: Optional[Decimal] = None
    RISK_MAX_ORDERS_PER_HOUR: Optional[int] = None
    RISK_DAILY_LOSS_LIMIT_QUOTE: Optional[Decimal] = None

    @classmethod
    def load(cls) -> "Settings":
        s = cls(
            MODE=_getenv_str("MODE", "paper").lower(),
            EXCHANGE=_getenv_str("EXCHANGE", "gateio"),
            SYMBOL=_getenv_str("SYMBOL", "BTC/USDT"),
            API_KEY=_getenv_str("API_KEY", ""),
            API_SECRET=_getenv_str("API_SECRET", ""),
            FIXED_AMOUNT=_getenv_decimal("FIXED_AMOUNT", Decimal("10")) or Decimal("10"),
            IDEMPOTENCY_BUCKET_MS=_getenv_int("IDEMPOTENCY_BUCKET_MS", 60_000),
            IDEMPOTENCY_TTL_SEC=_getenv_int("IDEMPOTENCY_TTL_SEC", 60),
            DB_PATH=_getenv_str("DB_PATH", ":memory:"),
            SERVER_PORT=_getenv_int("SERVER_PORT", 8000),

            # риск-гардрейлы
            RISK_COOLDOWN_SEC=_getenv_int("RISK_COOLDOWN_SEC", 30),
            RISK_MAX_SPREAD_PCT=_getenv_float("RISK_MAX_SPREAD_PCT", 0.3),
            RISK_MAX_POSITION_BASE=_getenv_decimal("RISK_MAX_POSITION_BASE", None),
            RISK_MAX_ORDERS_PER_HOUR=_getenv_int("RISK_MAX_ORDERS_PER_HOUR", 0) or None,
            RISK_DAILY_LOSS_LIMIT_QUOTE=_getenv_decimal("RISK_DAILY_LOSS_LIMIT_QUOTE", None),
        )

        errors = validate_settings(s)
        if errors:
            # ✅ теперь выбрасываем общий ValidationError, который ждут тесты
            raise ValidationError("Invalid settings: " + "; ".join(errors))
        return s

    def as_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)
