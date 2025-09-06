from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


class BollingerBandsStrategy(BaseStrategy):
    """Mean-reversion по полосам Боллинжера с детекцией «squeeze»."""

    def __init__(self, period: int = 20, std_dev: float = 2.0, squeeze_threshold: float = 0.01):
        self.period = int(period)
        self.std_dev = dec(str(std_dev))
        self.squeeze_threshold = dec(str(squeeze_threshold))
        self._prices: deque[Decimal] = deque(maxlen=self.period)

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            price = dec(str(ticker.get("last", "0")))
        else:
            price = dec(str(ctx.data.get("ticker", {}).get("last", "0")))

        if price <= 0:
            return Decision(action="hold", reason="no_price")

        self._prices.append(price)
        if len(self._prices) < self.period:
            return Decision(action="hold", reason="insufficient_data")

        sma = sum(self._prices) / dec(self.period)
        var = sum((p - sma) * (p - sma) for p in self._prices) / dec(self.period)
        std = dec(str(float(var) ** 0.5))
        upper = sma + std * self.std_dev
        lower = sma - std * self.std_dev
        width = (upper - lower) / sma if sma > 0 else dec("0")

        if width < self.squeeze_threshold:
            return Decision(action="hold", reason="squeeze")

        if price <= lower:
            return Decision(action="buy", confidence=0.65, reason="touch_lower_band")
        if price >= upper:
            return Decision(action="sell", confidence=0.65, reason="touch_upper_band")
        return Decision(action="hold", reason="within_bands")
