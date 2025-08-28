from __future__ import annotations

from collections import deque
from decimal import Decimal
from crypto_ai_bot.utils.decimal import dec
from typing import Any, Deque, Dict, Tuple

from .base import BaseStrategy, StrategyContext, Decision


class RSIMomentumStrategy(BaseStrategy):
    """RSI + Momentum: покупки при перепроданности с положительным моментумом и наоборот."""

    def __init__(self, rsi_period: int = 14, rsi_oversold: float = 30, rsi_overbought: float = 70, momentum_period: int = 10):
        self.rsi_period = rsi_period
        self.rsi_oversold = float(rsi_oversold)
        self.rsi_overbought = float(rsi_overbought)
        self.momentum_period = momentum_period

        self._prices: Deque[Decimal] = deque(maxlen=max(rsi_period, momentum_period) + 1)

    def _calc_rsi(self) -> Decimal:
        gains = dec("0")
        losses = dec("0")
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

    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        price = dec(str(ctx.data.get("ticker", {}).get("last", "0")))
        if price <= 0:
            return "hold", {"reason": "no_price"}

        self._prices.append(price)
        if len(self._prices) < max(self.rsi_period, self.momentum_period) + 1:
            return "hold", {"reason": "warming_up", "samples": len(self._prices)}

        rsi = self._calc_rsi()
        mom = self._calc_momentum()
        explain: Dict[str, Any] = {"rsi": float(rsi), "momentum_pct": float(mom), "oversold": self.rsi_oversold, "overbought": self.rsi_overbought}

        if float(rsi) < self.rsi_oversold and mom > 0:
            explain["signal"] = "oversold_with_positive_momentum"
            return "buy", explain
        if float(rsi) > self.rsi_overbought and mom < 0:
            explain["signal"] = "overbought_with_negative_momentum"
            return "sell", explain

        explain["signal"] = "neutral"
        return "hold", explain
