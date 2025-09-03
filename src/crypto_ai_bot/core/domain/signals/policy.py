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
        """ДћЕ“ДћВµГ‘вЂљДћВѕДћВґ ДћВєДћВ»ДћВ°Г‘ВЃГ‘ВЃДћВ° Policy ДћВґДћВ»Г‘ВЏ ДћВїГ‘в‚¬ДћВёДћВЅГ‘ВЏГ‘вЂљДћВёГ‘ВЏ Г‘в‚¬ДћВµГ‘Л†ДћВµДћВЅДћВёГ‘ВЏ."""
        score, explain = fuse_score(features)
        if score >= self.buy_threshold:
            return "buy", score, explain
        if score <= self.sell_threshold:
            return "sell", score, explain
        return "hold", score, explain


def decide(features: dict[str, Any], policy: Policy | None = None) -> tuple[str, float, str]:
    """ДћВ¤Г‘Ж’ДћВЅДћВєГ‘вЂ ДћВёГ‘ВЏ ДћВґДћВ»Г‘ВЏ ДћВѕДћВ±Г‘в‚¬ДћВ°Г‘вЂљДћВЅДћВѕДћВ№ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё: Г‘в‚¬ДћВµГ‘Л†ДћВµДћВЅДћВёДћВµ 'buy' | 'sell' | 'hold' + (score, explain)."""
    p = policy or Policy()
    return p.decide(features)
