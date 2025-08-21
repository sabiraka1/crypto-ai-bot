## `core/signals/policy.py`
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple
from ._fusion import fuse_score
@dataclass(frozen=True)
class Policy:
    buy_threshold: float = 0.62
    sell_threshold: float = 0.38
def decide(features: Dict[str, object], policy: Policy | None = None) -> Tuple[str, float, str]:
    """Решение 'buy' | 'sell' | 'hold' + (score, explain)."""
    p = policy or Policy()
    score, explain = fuse_score(features)
    if score >= p.buy_threshold:
        return "buy", score, explain
    if score <= p.sell_threshold:
        return "sell", score, explain
    return "hold", score, explain