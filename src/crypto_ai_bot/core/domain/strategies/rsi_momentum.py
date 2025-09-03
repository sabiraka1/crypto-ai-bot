from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec

from .base import BaseStrategy, Decision, MarketData, StrategyContext


class RSIMomentumStrategy(BaseStrategy):
    """RSI + Momentum: РїРѕРєСѓРїРєРё РїСЂРё РїРµСЂРµРїСЂРѕРґР°РЅРЅРѕСЃС‚Рё СЃ РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹Рј РјРѕРјРµРЅС‚СѓРјРѕРј Рё РЅР°РѕР±РѕСЂРѕС‚."""

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

    def decide(self, ctx: StrategyContext) -> tuple[str, dict[str, Any]]:
        data = ctx.data or {}
        price = dec(str(data.get("ticker", {}).get("last", "0")))
        if price <= 0:
            return "hold", {"reason": "no_price"}

        self._prices.append(price)
        if len(self._prices) < max(self.rsi_period, self.momentum_period) + 1:
            return "hold", {"reason": "warming_up", "samples": len(self._prices)}

        rsi = self._calc_rsi()
        mom = self._calc_momentum()
        explain: dict[str, Any] = {
            "rsi": float(rsi),
            "momentum_pct": float(mom),
            "oversold": self.rsi_oversold,
            "overbought": self.rsi_overbought,
        }

        if float(rsi) < self.rsi_oversold and mom > 0:
            explain["signal"] = "oversold_with_positive_momentum"
            return "buy", explain
        if float(rsi) > self.rsi_overbought and mom < 0:
            explain["signal"] = "overbought_with_negative_momentum"
            return "sell", explain

        explain["signal"] = "neutral"
        return "hold", explain

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        """РђРґР°РїС‚РµСЂ РґР»СЏ BaseStrategy.generate() - РІС‹Р·С‹РІР°РµС‚ decide() Рё РїСЂРµРѕР±СЂР°Р·СѓРµС‚ СЂРµР·СѓР»СЊС‚Р°С‚."""
        # РџРѕР»СѓС‡Р°РµРј РґР°РЅРЅС‹Рµ РёР· MarketData РµСЃР»Рё РёС… РЅРµС‚ РІ РєРѕРЅС‚РµРєСЃС‚Рµ
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            ctx = StrategyContext(symbol=ctx.symbol, settings=ctx.settings, data={"ticker": ticker})

        action, explain = self.decide(ctx)
        reason = explain.get("signal", explain.get("reason", ""))

        # Р’С‹С‡РёСЃР»СЏРµРј confidence РЅР° РѕСЃРЅРѕРІРµ СЃРёР»С‹ СЃРёРіРЅР°Р»Р°
        confidence = 0.5  # Р±Р°Р·РѕРІР°СЏ СѓРІРµСЂРµРЅРЅРѕСЃС‚СЊ
        if (
            action == "buy"
            and "oversold_with_positive_momentum" in reason
            or action == "sell"
            and "overbought_with_negative_momentum" in reason
        ):
            confidence = 0.7

        return Decision(action=action, confidence=confidence, reason=reason)
