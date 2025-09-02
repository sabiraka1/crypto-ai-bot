## `core/signals/policy.py`
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._fusion import fuse_score


@dataclass(frozen=True)
class Policy:
    buy_threshold: float = 0.62
    sell_threshold: float = 0.38
    
    def decide(self, features: dict[str, Any]) -> tuple[str, float, str]:
        """Метод класса Policy для принятия решения."""
        score, explain = fuse_score(features)
        if score >= self.buy_threshold:
            return "buy", score, explain
        if score <= self.sell_threshold:
            return "sell", score, explain
        return "hold", score, explain


def decide(features: dict[str, Any], policy: Policy | None = None) -> tuple[str, float, str]:
    """Функция для обратной совместимости: решение 'buy' | 'sell' | 'hold' + (score, explain)."""
    p = policy or Policy()
    return p.decide(features)