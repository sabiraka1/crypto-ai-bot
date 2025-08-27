from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any, Deque, Dict, Tuple

from .base import BaseStrategy, StrategyContext, Decision


class BollingerBandsStrategy(BaseStrategy):
    """Mean-reversion по полосам Боллинджера с детекцией 'squeeze'."""

    def __init__(self, period: int = 20, std_dev: float = 2.0, squeeze_threshold: float = 0.01):
        self.period = int(period)
        self.std_dev = Decimal(str(std_dev))
        self.squeeze_threshold = Decimal(str(squeeze_threshold))
        self._prices: Deque[Decimal] = deque(maxlen=self.period)

    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        price = Decimal(str(ctx.data.get("ticker", {}).get("last", "0")))
        self._prices.append(price)

        if len(self._prices) < self.period:
            return "hold", {"reason": "insufficient_data", "samples": len(self._prices)}

        sma = sum(self._prices) / Decimal(self.period)
        var = sum((p - sma) * (p - sma) for p in self._prices) / Decimal(self.period)
        # корень через float для скорости/простоты
        std = Decimal(str(float(var) ** 0.5))

        upper = sma + std * self.std_dev
        lower = sma - std * self.std_dev
        width = (upper - lower) / sma if sma > 0 else Decimal("0")

        explain: Dict[str, Any] = {"price": float(price), "upper": float(upper), "middle": float(sma), "lower": float(lower), "width": float(width)}

        if width < self.squeeze_threshold:
            explain["signal"] = "squeeze"
            return "hold", explain

        if price <= lower:
            explain["signal"] = "touch_lower_band"
            return "buy", explain
        if price >= upper:
            explain["signal"] = "touch_upper_band"
            return "sell", explain

        explain["signal"] = "within_bands"
        return "hold", explain
