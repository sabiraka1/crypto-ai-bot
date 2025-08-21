# src/crypto_ai_bot/core/settings.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List
from crypto_ai_bot.core.validators.settings import validate_settings
from crypto_ai_bot.utils.exceptions import ValidationError


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(slots=True)
class Settings:
    """Единственный источник конфигурации.
    - Читает все ENV здесь (нигде больше);
    - Валидирует режимы и ключи для live;
    - Предоставляет типизированный доступ.
    """
    MODE: str = "paper"                 # 'paper' | 'live'
    EXCHANGE: str = "gate.io"
    SYMBOLS: List[str] = field(default_factory=lambda: _csv("SYMBOLS", "BTC/USDT"))
    FIXED_AMOUNT: float = float(os.environ.get("FIXED_AMOUNT", 10.0))

    # БД
    DB_PATH: str = os.environ.get("DB_PATH", "crypto_ai_bot.db")

    # Идемпотентность / интервалы
    IDEMPOTENCY_TTL_SEC: int = int(os.environ.get("IDEMPOTENCY_TTL_SEC", 60))

    EVAL_INTERVAL_SEC: int = int(os.environ.get("EVAL_INTERVAL_SEC", 60))
    EXITS_INTERVAL_SEC: int = int(os.environ.get("EXITS_INTERVAL_SEC", 5))
    RECONCILE_INTERVAL_SEC: int = int(os.environ.get("RECONCILE_INTERVAL_SEC", 60))
    WATCHDOG_INTERVAL_SEC: int = int(os.environ.get("WATCHDOG_INTERVAL_SEC", 15))

    # Интеграции (live)
    API_KEY: str | None = os.environ.get("API_KEY") or None
    API_SECRET: str | None = os.environ.get("API_SECRET") or None
    API_PASSWORD: str | None = os.environ.get("API_PASSWORD") or None

    # Логи/метрики
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    @classmethod
    def load(cls) -> "Settings":
        """Загружает и валидирует конфигурацию из ENV."""
        s = cls()
        # Нормализуем поля
        s.MODE = str(s.MODE).lower()
        s.EXCHANGE = str(s.EXCHANGE).lower()
        # Валидация через core/validators
        errors = validate_settings(s)
        if errors:
            raise ValidationError("; ".join(errors))
        return s

    def as_dict(self) -> dict:
        return {
            "MODE": self.MODE,
            "EXCHANGE": self.EXCHANGE,
            "SYMBOLS": list(self.SYMBOLS),
            "FIXED_AMOUNT": self.FIXED_AMOUNT,
            "DB_PATH": self.DB_PATH,
            "IDEMPOTENCY_TTL_SEC": self.IDEMPOTENCY_TTL_SEC,
            "EVAL_INTERVAL_SEC": self.EVAL_INTERVAL_SEC,
            "EXITS_INTERVAL_SEC": self.EXITS_INTERVAL_SEC,
            "RECONCILE_INTERVAL_SEC": self.RECONCILE_INTERVAL_SEC,
            "WATCHDOG_INTERVAL_SEC": self.WATCHDOG_INTERVAL_SEC,
            "LOG_LEVEL": self.LOG_LEVEL,
            "API_KEY?": bool(self.API_KEY),
            "API_SECRET?": bool(self.API_SECRET),
        }
