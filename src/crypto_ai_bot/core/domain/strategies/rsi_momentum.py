from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


class RSIMomentumStrategy(BaseStrategy):
    """RSI + Momentum: покупки при перепроданности с положительным моментумом и наоборот."""

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        momentum_period: int = 10,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = float(rsi_oversold)
        self.rsi_overbought = float(rsi_overbought)
        self.momentum_period = momentum_period
        self._prices: deque[Decimal] = deque(maxlen=max(rsi_period, momentum_period) + 1)

    def _calc_rsi(self) -> Decimal:
        gains = dec("0")
        losses = dec("0")
        # упрощённый RSI по сумме позитивных/негативных изменений
        for i in range(1, len(self._prices)):
            diff = self._prices[i] - self._prices[i - 1]
            if diff > 0:
                gains += diff
            elif diff < 0:
                losses += -diff
        if len(self._prices) <= 1:
            return dec("50")
        avg_gain = gains / dec(self.rsi_period)
        avg_loss = losses / dec(self.rsi_period) if losses > 0 else dec("0")
        if avg_loss == 0:
            return dec("100")
        rs = avg_gain / avg_loss
        return dec("100") - (dec("100") / (dec("1") + rs))

    def _calc_momentum(self) -> Decimal:
        if len(self._prices) < self.momentum_period + 1:
            return dec("0")
        cur = self._prices[-1]
        past = self._prices[-1 - self.momentum_period]
        if past == 0:
            return dec("0")
        return ((cur - past) / past) * dec("100")

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            price = dec(str(ticker.get("last", "0")))
        else:
            price = dec(str(ctx.data.get("ticker", {}).get("last", "0")))

        if price <= 0:
            return Decision(action="hold", reason="no_price")

        self._prices.append(price)
        if len(self._prices) < max(self.rsi_period, self.momentum_period) + 1:
            return Decision(action="hold", reason="warming_up")

        rsi = self._calc_rsi()
        mom = self._calc_momentum()

        if float(rsi) < self.rsi_oversold and mom > 0:
            return Decision(action="buy", confidence=0.7, reason="oversold_with_positive_momentum")
        if float(rsi) > self.rsi_overbought and mom < 0:
            return Decision(action="sell", confidence=0.7, reason="overbought_with_negative_momentum")
        return Decision(action="hold", reason="neutral")
