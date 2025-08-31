from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Signal:
    """
    Торговый сигнал от стратегии.
    action: 'buy' | 'sell' | 'hold'
    confidence: 0..1 (вес сигнала)
    quote_amount: желаемая сумма в котируемой валюте (для buy)
    base_amount: желаемое количество базовой валюты (для sell)
    reason: текстовая причина (для логов/алёртов)
    """
    action: str = "hold"
    confidence: float = 0.0
    quote_amount: str | None = None
    base_amount: str | None = None
    reason: str = ""


class MarketDataPort(Protocol):
    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1m", limit: int = 200
    ) -> Sequence[tuple]:
        """
        Возвращает последовательность свечей: (ts_ms, open, high, low, close, volume)
        Значения числовые (float/str приводимые к Decimal).
        """
        ...

    async def get_ticker(self, symbol: str) -> dict:
        """Возвращает тикер с полями bid/ask/last и т.п."""
        ...


class StrategyPort(Protocol):
    async def generate(self, *, symbol: str, md: MarketDataPort, settings: Any) -> Signal:
        """Вернуть торговый сигнал для symbol, используя md и настройки."""
        ...
