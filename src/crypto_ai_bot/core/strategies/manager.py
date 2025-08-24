from __future__ import annotations

from typing import Dict, Tuple

from .base import BaseStrategy, StrategyContext, Decision
from .ema_cross import EmaCrossStrategy


class StrategyManager:
    """
    Тонкий менеджер стратегий: выбирает стратегию и дергает decide().
    Никакой скрытой магии — по умолчанию EmaCrossStrategy.
    """

    def __init__(self, strategy: BaseStrategy | None = None) -> None:
        self._strategy = strategy or EmaCrossStrategy()

    def decide(self, *, symbol: str, exchange: str, context: Dict) -> Tuple[Decision, Dict]:
        ctx = StrategyContext(symbol=symbol, exchange=exchange, data=context)
        return self._strategy.decide(ctx)


def choose_default_strategy() -> StrategyManager:
    return StrategyManager(EmaCrossStrategy())
