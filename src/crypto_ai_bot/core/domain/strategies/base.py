from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, TypedDict
from enum import Enum


# Внешний контракт НЕ ломаем: решение остаётся строкой.
Decision = str  # "buy" | "sell" | "hold"


class DecisionEnum(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class MarketData(TypedDict, total=False):
    ticker: Dict[str, Decimal]            # {"last": Decimal, "bid": Decimal, "ask": Decimal, "timestamp": int}
    spread: float                          # %
    sma_fast: Optional[Decimal]
    sma_slow: Optional[Decimal]
    volatility_pct: float                  # %
    samples: int


@dataclass
class StrategyContext:
    symbol: str
    exchange: str
    data: MarketData  # market context (build_market_context)


class BaseStrategy(ABC):
    @abstractmethod
    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        """Вернуть (решение, объяснение). Решение: 'buy'|'sell'|'hold'."""
        raise NotImplementedError
