from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Tuple

Decision = str  # "buy" | "sell" | "hold"


@dataclass
class StrategyContext:
    symbol: str
    exchange: str
    data: Dict[str, Any]  # то, что собрали в signals/_build.py


class BaseStrategy(ABC):
    """Базовый интерфейс стратегии. Никаких внешних зависимостей."""

    @abstractmethod
    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        """Вернуть (решение, объяснение)."""
        raise NotImplementedError
