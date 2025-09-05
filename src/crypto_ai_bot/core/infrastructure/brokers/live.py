from __future__ import annotations

from dataclasses import dataclass

from .ccxt_adapter import CcxtBroker


@dataclass
class LiveBroker(CcxtBroker):
    """Живая обёртка для CCXT-брокера: принудительно включает live-режим (dry_run=False)."""

    def __post_init__(self) -> None:
        # Важно: сначала выставляем флаги live-режима, затем зовём базовый __post_init__,
        # чтобы он инициализировал CCXT уже в «боевом» режиме.
        try:
            # Если базовый dataclass заморожен (frozen=True), используем object.__setattr__
            if hasattr(self, "dry_run"):
                object.__setattr__(self, "dry_run", False)
            if hasattr(self, "mode"):
                object.__setattr__(self, "mode", "live")
        except Exception:
            # На случай незамороженного dataclass — обычная установка
            self.dry_run = False  # type: ignore[attr-defined]
            if hasattr(self, "mode"):
                self.mode = "live"  # type: ignore[attr-defined]

        super().__post_init__()

        # Мягкая проверка, что учётки для live заданы
        try:
            api_key = getattr(self, "api_key", None)
            api_secret = getattr(self, "api_secret", None) or getattr(self, "secret", None)
            if not api_key or not api_secret:
                from crypto_ai_bot.utils.logging import get_logger
                get_logger(__name__).warning(
                    "live_broker_missing_credentials",
                    extra={"exchange": getattr(self, "exchange", None)},
                )
        except Exception:
            # Логгер не критичен для старта live-брокера
            pass
