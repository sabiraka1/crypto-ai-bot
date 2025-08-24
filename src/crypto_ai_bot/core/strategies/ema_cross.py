from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

from .base import BaseStrategy, StrategyContext, Decision


def _to_dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


class EmaCrossStrategy(BaseStrategy):
    """
    Реально — кроссовер на скользящих (используем уже собранные SMA из контекста,
    чтобы не плодить состояние). Порог ±0.1% против медленной.
    Решение: "buy" | "sell" | "hold".
    """

    def __init__(self, threshold_pct: float = 0.1) -> None:
        self._thr = Decimal(str(threshold_pct)) / Decimal("100")

    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        d = ctx.data
        sma_fast = d.get("sma_fast")
        sma_slow = d.get("sma_slow")
        explain: Dict[str, Any] = {
            "samples": int(d.get("samples") or 0),
            "spread": float(d.get("spread") or 0.0),
            "volatility_pct": float(d.get("volatility_pct") or 0.0),
            "rule": "",
        }

        if sma_fast is not None and sma_slow is not None:
            fast = _to_dec(sma_fast)
            slow = _to_dec(sma_slow)
            up = slow * (Decimal("1") + self._thr)
            dn = slow * (Decimal("1") - self._thr)

            if fast > up:
                explain["rule"] = "fast>slow*(1+thr)"
                return "buy", explain
            if fast < dn:
                explain["rule"] = "fast<slow*(1-thr)"
                return "sell", explain
            explain["rule"] = "hold_sma_flat"
            return "hold", explain

        explain["rule"] = "hold_insufficient_history"
        return "hold", explain
