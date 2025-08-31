from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("protective_exits")


@dataclass(frozen=True)
class ExitConfig:
    """
    Конфиг защитных выходов. Значения читаются из settings.
      - stop/take/trailing — флаги включения подсистем
      - max_slippage_pct — sanity-ограничитель, чтобы не закрываться по «дикой» цене
    """
    stop_enabled: bool = True
    take_enabled: bool = True
    trailing_enabled: bool = True
    max_slippage_pct: Decimal = dec("1.0")  # в процентах


class ProtectiveExits:
    """
    Безопасная реализация по умолчанию, чтобы сервис гарантированно стартовал.
    Если в проекте позже появятся конкретные правила SL/TP/Trailing,
    их можно расширить в методе evaluate() — внешние контракты не меняем.
    """

    def __init__(self, *, broker: Any, storage: Any, bus: Any, settings: Any) -> None:
        self._broker = broker
        self._storage = storage
        self._bus = bus
        self._settings = settings
        self._cfg = ExitConfig(
            stop_enabled=bool(int(getattr(settings, "EXITS_STOP_ENABLED", 1) or 1)),
            take_enabled=bool(int(getattr(settings, "EXITS_TAKE_ENABLED", 1) or 1)),
            trailing_enabled=bool(int(getattr(settings, "EXITS_TRAILING_ENABLED", 1) or 1)),
            max_slippage_pct=dec(str(getattr(settings, "RISK_MAX_SLIPPAGE_PCT", "1.0") or "1.0")),
        )
        _log.info(
            "protective_exits.init",
            extra={
                "stop": self._cfg.stop_enabled,
                "take": self._cfg.take_enabled,
                "trailing": self._cfg.trailing_enabled,
                "max_slippage_pct": str(self._cfg.max_slippage_pct),
            },
        )

    async def start(self) -> None:
        """Хук для фонового запуска (если нужен цикл). По умолчанию — ничего не делаем."""
        _log.debug("protective_exits.start")

    async def stop(self) -> None:
        """Остановка фоновой работы."""
        _log.debug("protective_exits.stop")

    async def evaluate(self, *, symbol: str) -> dict | None:
        """
        Основная точка входа из оркестратора: проверить, нужна ли защитная
        фиксация позиции (SL/TP/Trailing). Возвращает dict-результат или None.

        Текущая минимальная реализация — «no-op»:
        - ничего не ломает,
        - позволяет сервису стартовать и работать,
        - сохраняет контракт для будущего расширения.
        """
        try:
            if not (self._cfg.stop_enabled or self._cfg.take_enabled or self._cfg.trailing_enabled):
                return None

            # Пример будущей логики:
            # 1) прочитать текущую позицию/цены из storage/broker
            # 2) рассчитать, нужно ли двигать/ставить стоп или фиксировать профит
            # 3) при необходимости — создать рыночный ордер на закрытие/частичную фиксацию
            # Сейчас — только метрика «живости».
            inc("protective_exits_tick_total", symbol=symbol)
            return None
        except Exception:
            _log.error("protective_exits.evaluate_failed", extra={"symbol": symbol}, exc_info=True)
            return None


# Фабрика (на случай, если где-то вызывается именно функция)
def make_protective_exits(*, broker: Any, storage: Any, bus: Any, settings: Any) -> ProtectiveExits:
    return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)
