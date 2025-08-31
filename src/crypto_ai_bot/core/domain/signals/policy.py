## `core/signals/policy.py`
from __future__ import annotations

from dataclasses import dataclass

from ._fusion import fuse_score


@dataclass(frozen=True)
class Policy:
    buy_threshold: float = 0.62
    sell_threshold: float = 0.38
def decide(features: dict[str, object], policy: Policy | None = None) -> tuple[str, float, str]:
    """Решение 'buy' | 'sell' | 'hold' + (score, explain)."""
    p = policy or Policy()
    score, explain = fuse_score(features)
    if score >= p.buy_threshold:
        return "buy", score, explain
    if score <= p.sell_threshold:
        return "sell", score, explain
    return "hold", score, explain
