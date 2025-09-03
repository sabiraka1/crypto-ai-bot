from __future__ import annotations

from typing import Any

from crypto_ai_bot.core.domain.strategies.base import BaseStrategy, Decision, MarketData
from crypto_ai_bot.core.domain.strategies.ema_atr import EmaAtrConfig, EmaAtrStrategy
from crypto_ai_bot.utils.decimal import dec


# РЎРѕР·РґР°РµРј Р°Р»РёР°СЃС‹ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃРѕ СЃС‚Р°СЂС‹Рј РєРѕРґРѕРј
MarketData = MarketData
StrategyPort = BaseStrategy
Signal = Decision


class StrategyManager:
    """
    РђРіСЂРµРіР°С‚РѕСЂ СЃС‚СЂР°С‚РµРіРёР№.
    РќР° РїРµСЂРІРѕРј СЌС‚Р°РїРµ вЂ” РѕРґРёРЅ СЃРёРіРЅР°Р» (EMA+ATR). РџРѕР·Р¶Рµ РјРѕР¶РЅРѕ РґРѕР±Р°РІР»СЏС‚СЊ РґСЂСѓРіРёРµ
    Рё Р°РіСЂРµРіРёСЂРѕРІР°С‚СЊ (РІР·РІРµС€РёРІР°РЅРёРµ/РїСЂРёРѕСЂРёС‚РµС‚С‹).
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
        # РџСЂРѕСЃС‚РѕР№ РїСЂРёРѕСЂРёС‚РµС‚: РїРµСЂРІР°СЏ, РґР°РІС€Р°СЏ directional-СЃРёРіРЅР°Р»
        for strat in self._strategies:
            from crypto_ai_bot.core.domain.strategies.base import StrategyContext
            ctx = StrategyContext(symbol=symbol, settings=self._settings)
            sig = await strat.generate(md=self._md, ctx=ctx)
            if sig.action in ("buy", "sell"):
                return sig
        return Signal(action="hold", reason="all_hold")
