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
        """ĞœĞµÑ‚Ğ¾Ğ´ ĞºĞ»Ğ°ÑÑĞ° Policy Ğ´Ğ»Ñ Ğ¿Ñ€Ğ¸Ğ½ÑÑ‚Ğ¸Ñ Ñ€ĞµÑˆĞµĞ½Ğ¸Ñ."""
        score, explain = fuse_score(features)
        if score >= self.buy_threshold:
            return "buy", score, explain
        if score <= self.sell_threshold:
            return "sell", score, explain
        return "hold", score, explain


def decide(features: dict[str, Any], policy: Policy | None = None) -> tuple[str, float, str]:
    """Ğ¤ÑƒĞ½ĞºÑ†Ğ¸Ñ Ğ´Ğ»Ñ Ğ¾Ğ±Ñ€Ğ°Ñ‚Ğ½Ğ¾Ğ¹ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸: Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ 'buy' | 'sell' | 'hold' + (score, explain)."""
    p = policy or Policy()
    return p.decide(features)
