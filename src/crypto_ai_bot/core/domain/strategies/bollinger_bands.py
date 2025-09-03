from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec

from .base import BaseStrategy, Decision, MarketData, StrategyContext


class BollingerBandsStrategy(BaseStrategy):
    """Mean-reversion РїРѕ РїРѕР»РѕСЃР°Рј Р‘РѕР»Р»РёРЅРґР¶РµСЂР° СЃ РґРµС‚РµРєС†РёРµР№ 'squeeze'."""

    def __init__(self, period: int = 20, std_dev: float = 2.0, squeeze_threshold: float = 0.01):
        self.period = int(period)
        self.std_dev = dec(str(std_dev))
        self.squeeze_threshold = dec(str(squeeze_threshold))
        self._prices: deque[Decimal] = deque(maxlen=self.period)

    def decide(self, ctx: StrategyContext) -> tuple[str, dict[str, Any]]:
        data = ctx.data or {}
        price = dec(str(data.get("ticker", {}).get("last", "0")))
        self._prices.append(price)

        if len(self._prices) < self.period:
            return "hold", {"reason": "insufficient_data", "samples": len(self._prices)}

        sma = sum(self._prices) / dec(self.period)
        var = sum((p - sma) * (p - sma) for p in self._prices) / dec(self.period)
        # РєРѕСЂРµРЅСЊ С‡РµСЂРµР· float РґР»СЏ СЃРєРѕСЂРѕСЃС‚Рё/РїСЂРѕСЃС‚РѕС‚С‹
        std = dec(str(float(var) ** 0.5))

        upper = sma + std * self.std_dev
        lower = sma - std * self.std_dev
        width = (upper - lower) / sma if sma > 0 else dec("0")

        explain: dict[str, Any] = {
            "price": float(price),
            "upper": float(upper),
            "middle": float(sma),
            "lower": float(lower),
            "width": float(width),
        }

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

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        """РђРґР°РїС‚РµСЂ РґР»СЏ BaseStrategy.generate() - РІС‹Р·С‹РІР°РµС‚ decide() Рё РїСЂРµРѕР±СЂР°Р·СѓРµС‚ СЂРµР·СѓР»СЊС‚Р°С‚."""
        # РџРѕР»СѓС‡Р°РµРј РґР°РЅРЅС‹Рµ РёР· MarketData РµСЃР»Рё РёС… РЅРµС‚ РІ РєРѕРЅС‚РµРєСЃС‚Рµ
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            ctx = StrategyContext(symbol=ctx.symbol, settings=ctx.settings, data={"ticker": ticker})

        action, explain = self.decide(ctx)
        reason = explain.get("signal", explain.get("reason", ""))

        # Р’С‹С‡РёСЃР»СЏРµРј confidence РЅР° РѕСЃРЅРѕРІРµ СЃРёР»С‹ СЃРёРіРЅР°Р»Р°
        confidence = 0.5
        if action in ["buy", "sell"] and "touch" in reason:
            confidence = 0.65

        return Decision(action=action, confidence=confidence, reason=reason)
