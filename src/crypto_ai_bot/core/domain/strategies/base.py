from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


# ==== Совместимый публичный API для стратегий ====

@dataclass(frozen=True)
class Decision:
    """
    Решение стратегии:
    - action: 'buy' | 'sell' | 'hold'
    - confidence: 0..1 (вес)
    - quote_amount/base_amount: желаемые объёмы
    - reason: пояснение (для логов/уведомлений)
    """
    action: str
    confidence: float = 0.0
    quote_amount: str | None = None
    base_amount: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class StrategyContext:
    """Контекст генерации сигнала."""
    symbol: str
    settings: Any
    data: dict[str, Any] | None = None  # Добавлен для совместимости с существующим кодом


class MarketData(Protocol):
    """Порт для получения рыночных данных."""
    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1m", limit: int = 200
    ) -> Sequence[tuple[Any, ...]]: ...
    async def get_ticker(self, symbol: str) -> dict[str, Any]: ...


# Для совместимости со старым именованием:
MarketDataPort = MarketData


class BaseStrategy(ABC):
    """Базовый контракт стратегии."""

    @abstractmethod
    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision: ...
    
    # Добавляем метод decide для обратной совместимости
    def decide(self, ctx: StrategyContext) -> tuple[str, dict[str, Any]]:
        """Легаси метод для совместимости со старым кодом."""
        # Будет переопределен в конкретных стратегиях
        return "hold", {"reason": "not_implemented"}