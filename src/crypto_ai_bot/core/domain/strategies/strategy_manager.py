from __future__ import annotations

from typing import Any

from crypto_ai_bot.core.domain.strategies.base import BaseStrategy, Decision, MarketData
from crypto_ai_bot.core.domain.strategies.ema_atr import EmaAtrConfig, EmaAtrStrategy
from crypto_ai_bot.utils.decimal import dec

# Ğ Â Ğ Ğ‹Ğ Â Ğ¡â€¢Ğ Â Ğ’Â·Ğ Â Ğ¢â€˜Ğ Â Ğ’Â°Ğ Â Ğ’ÂµĞ Â Ğ¡Â˜ Ğ Â Ğ’Â°Ğ Â Ğ’Â»Ğ Â Ğ¡â€˜Ğ Â Ğ’Â°Ğ ĞĞ Ñ“Ğ ĞĞ²Ğ‚â„– Ğ Â Ğ¢â€˜Ğ Â Ğ’Â»Ğ ĞĞ Ğ Ğ ĞĞ Ñ“Ğ Â Ğ¡â€¢Ğ Â Ğ â€ Ğ Â Ğ¡Â˜Ğ Â Ğ’ÂµĞ ĞĞ Ñ“Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ¡â€˜Ğ Â Ğ¡Â˜Ğ Â Ğ¡â€¢Ğ ĞĞ Ñ“Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ¡â€˜ Ğ ĞĞ Ñ“Ğ Â Ğ¡â€¢ Ğ ĞĞ Ñ“Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ’Â°Ğ ĞĞ â€šĞ ĞĞ²Ğ‚â„–Ğ Â Ğ¡Â˜ Ğ Â Ğ¡â€Ğ Â Ğ¡â€¢Ğ Â Ğ¢â€˜Ğ Â Ğ¡â€¢Ğ Â Ğ¡Â˜
MarketData = MarketData
StrategyPort = BaseStrategy
Signal = Decision


class StrategyManager:
    """
    Ğ Â Ğ¡â€™Ğ Â Ğ¡â€“Ğ ĞĞ â€šĞ Â Ğ’ÂµĞ Â Ğ¡â€“Ğ Â Ğ’Â°Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ¡â€¢Ğ ĞĞ â€š Ğ ĞĞ Ñ“Ğ ĞĞ²Ğ‚Ñ™Ğ ĞĞ â€šĞ Â Ğ’Â°Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ’ÂµĞ Â Ğ¡â€“Ğ Â Ğ¡â€˜Ğ Â Ğ²â€â€“.
    Ğ Â Ğ¡ÑšĞ Â Ğ’Â° Ğ Â Ğ¡â€”Ğ Â Ğ’ÂµĞ ĞĞ â€šĞ Â Ğ â€ Ğ Â Ğ¡â€¢Ğ Â Ğ¡Â˜ Ğ ĞĞ ĞŠĞ ĞĞ²Ğ‚Ñ™Ğ Â Ğ’Â°Ğ Â Ğ¡â€”Ğ Â Ğ’Âµ Ğ Ğ†Ğ â€šĞ²Ğ‚Ñœ Ğ Â Ğ¡â€¢Ğ Â Ğ¢â€˜Ğ Â Ğ¡â€˜Ğ Â Ğ â€¦ Ğ ĞĞ Ñ“Ğ Â Ğ¡â€˜Ğ Â Ğ¡â€“Ğ Â Ğ â€¦Ğ Â Ğ’Â°Ğ Â Ğ’Â» (EMA+ATR). Ğ Â Ğ¡ÑŸĞ Â Ğ¡â€¢Ğ Â Ğ’Â·Ğ Â Ğ’Â¶Ğ Â Ğ’Âµ Ğ Â Ğ¡Â˜Ğ Â Ğ¡â€¢Ğ Â Ğ’Â¶Ğ Â Ğ â€¦Ğ Â Ğ¡â€¢ Ğ Â Ğ¢â€˜Ğ Â Ğ¡â€¢Ğ Â Ğ’Â±Ğ Â Ğ’Â°Ğ Â Ğ â€ Ğ Â Ğ’Â»Ğ ĞĞ ĞĞ ĞĞ²Ğ‚Ñ™Ğ ĞĞ Ğ‰ Ğ Â Ğ¢â€˜Ğ ĞĞ â€šĞ ĞĞ¡â€œĞ Â Ğ¡â€“Ğ Â Ğ¡â€˜Ğ Â Ğ’Âµ
    Ğ Â Ğ¡â€˜ Ğ Â Ğ’Â°Ğ Â Ğ¡â€“Ğ ĞĞ â€šĞ Â Ğ’ÂµĞ Â Ğ¡â€“Ğ Â Ğ¡â€˜Ğ ĞĞ â€šĞ Â Ğ¡â€¢Ğ Â Ğ â€ Ğ Â Ğ’Â°Ğ ĞĞ²Ğ‚Ñ™Ğ ĞĞ Ğ‰ (Ğ Â Ğ â€ Ğ Â Ğ’Â·Ğ Â Ğ â€ Ğ Â Ğ’ÂµĞ ĞĞ²â€šÂ¬Ğ Â Ğ¡â€˜Ğ Â Ğ â€ Ğ Â Ğ’Â°Ğ Â Ğ â€¦Ğ Â Ğ¡â€˜Ğ Â Ğ’Âµ/Ğ Â Ğ¡â€”Ğ ĞĞ â€šĞ Â Ğ¡â€˜Ğ Â Ğ¡â€¢Ğ ĞĞ â€šĞ Â Ğ¡â€˜Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ’ÂµĞ ĞĞ²Ğ‚Ñ™Ğ ĞĞ²Ğ‚â„–).
    """

    def __init__(self, *, md: MarketData, settings: Any) -> None:
        self._md = md
        self._settings = settings
        self._strategies: list[StrategyPort] = []
        self._load_strategies()

    def _load_strategies(self) -> None:
        if not getattr(self._settings, "STRATEGY_ENABLED", True):
            return
        names = str(getattr(self._settings, "STRATEGY_SET", "ema_atr") or "ema_atr")
        for name in [x.strip().lower() for x in names.split(",") if x.strip()]:
            if name == "ema_atr":
                cfg = EmaAtrConfig(
                    ema_short=int(getattr(self._settings, "EMA_SHORT", 12) or 12),
                    ema_long=int(getattr(self._settings, "EMA_LONG", 26) or 26),
                    atr_period=int(getattr(self._settings, "ATR_PERIOD", 14) or 14),
                    atr_max_pct=dec(str(getattr(self._settings, "ATR_MAX_PCT", "1000") or "1000")),
                    ema_min_slope=dec(str(getattr(self._settings, "EMA_MIN_SLOPE", "0") or "0")),
                )
                self._strategies.append(EmaAtrStrategy(cfg))

    async def decide(self, symbol: str) -> Signal:
        if not self._strategies:
            return Signal(action="hold", reason="no_strategies")
        # Ğ Â Ğ¡ÑŸĞ ĞĞ â€šĞ Â Ğ¡â€¢Ğ ĞĞ Ñ“Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ¡â€¢Ğ Â Ğ²â€â€“ Ğ Â Ğ¡â€”Ğ ĞĞ â€šĞ Â Ğ¡â€˜Ğ Â Ğ¡â€¢Ğ ĞĞ â€šĞ Â Ğ¡â€˜Ğ ĞĞ²Ğ‚Ñ™Ğ Â Ğ’ÂµĞ ĞĞ²Ğ‚Ñ™: Ğ Â Ğ¡â€”Ğ Â Ğ’ÂµĞ ĞĞ â€šĞ Â Ğ â€ Ğ Â Ğ’Â°Ğ ĞĞ Ğ, Ğ Â Ğ¢â€˜Ğ Â Ğ’Â°Ğ Â Ğ â€ Ğ ĞĞ²â€šÂ¬Ğ Â Ğ’Â°Ğ ĞĞ Ğ directional-Ğ ĞĞ Ñ“Ğ Â Ğ¡â€˜Ğ Â Ğ¡â€“Ğ Â Ğ â€¦Ğ Â Ğ’Â°Ğ Â Ğ’Â»
        for strat in self._strategies:
            from crypto_ai_bot.core.domain.strategies.base import StrategyContext

            ctx = StrategyContext(symbol=symbol, settings=self._settings)
            sig = await strat.generate(md=self._md, ctx=ctx)
            if sig.action in ("buy", "sell"):
                return sig
        return Signal(action="hold", reason="all_hold")
