from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Settings:
    # общие
    MODE: str = "paper"                      # "paper" | "live"
    EXCHANGE: str = "gateio"
    SYMBOL: str = "BTC/USDT"

    # торговые параметры
    FIXED_AMOUNT: float = 0.001
    IDEMPOTENCY_TTL_SEC: int = 60
    EVAL_INTERVAL_SEC: int = 15
    EXITS_INTERVAL_SEC: int = 30
    RECONCILE_INTERVAL_SEC: int = 60

    # доступ к бирже
    API_KEY: str = ""
    API_SECRET: str = ""

    # Telegram (опционально)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_SECRET: str = ""

    # база (опционально; если нет — можно работать без БД)
    DB_PATH: str = "bot.db"

    @classmethod
    def from_env(cls) -> "Settings":
        def _get(name: str, default: str) -> str:
            return os.getenv(name, default)

        def _get_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except Exception:
                return default

        def _get_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except Exception:
                return default

        return cls(
            MODE=_get("MODE", cls.MODE),
            EXCHANGE=_get("EXCHANGE", cls.EXCHANGE),
            SYMBOL=_get("SYMBOL", cls.SYMBOL),
            FIXED_AMOUNT=_get_float("FIXED_AMOUNT", cls.FIXED_AMOUNT),
            IDEMPOTENCY_TTL_SEC=_get_int("IDEMPOTENCY_TTL_SEC", cls.IDEMPOTENCY_TTL_SEC),
            EVAL_INTERVAL_SEC=_get_int("EVAL_INTERVAL_SEC", cls.EVAL_INTERVAL_SEC),
            EXITS_INTERVAL_SEC=_get_int("EXITS_INTERVAL_SEC", cls.EXITS_INTERVAL_SEC),
            RECONCILE_INTERVAL_SEC=_get_int("RECONCILE_INTERVAL_SEC", cls.RECONCILE_INTERVAL_SEC),
            API_KEY=_get("API_KEY", cls.API_KEY),
            API_SECRET=_get("API_SECRET", cls.API_SECRET),
            TELEGRAM_BOT_TOKEN=_get("TELEGRAM_BOT_TOKEN", cls.TELEGRAM_BOT_TOKEN),
            TELEGRAM_BOT_SECRET=_get("TELEGRAM_BOT_SECRET", cls.TELEGRAM_BOT_SECRET),
            DB_PATH=_get("DB_PATH", cls.DB_PATH),
        )

    def is_live(self) -> bool:
        return str(self.MODE).lower() == "live"

    def validate(self) -> List[str]:
        """
        Мини-валидация настроек (использует validators, если он есть).
        """
        try:
            from crypto_ai_bot.core.validators.settings import validate_trading_params
        except Exception:
            validate_trading_params = None  # type: ignore
        if validate_trading_params:
            return validate_trading_params(self)
        # разумные базовые проверки, если валидатор отсутствует
        errors: List[str] = []
        if self.is_live() and (not self.API_KEY or not self.API_SECRET):
            errors.append("MODE=live требует API_KEY и API_SECRET")
        if self.IDEMPOTENCY_TTL_SEC <= 0:
            errors.append("IDEMPOTENCY_TTL_SEC must be > 0")
        if self.FIXED_AMOUNT <= 0:
            errors.append("FIXED_AMOUNT must be > 0")
        return errors
