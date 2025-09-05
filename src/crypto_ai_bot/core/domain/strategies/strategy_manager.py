from __future__ import annotations

from typing import Any

from crypto_ai_bot.core.domain.strategies.base_strategy import BaseStrategy, Decision, MarketData
from crypto_ai_bot.core.domain.strategies.ema_atr import EmaAtrConfig, EmaAtrStrategy
from crypto_ai_bot.utils.decimal import dec

# Р РЋР С•Р В·Р Т‘Р В°Р ВµР С Р В°Р В»Р С‘Р В°РЎРѓРЎвЂ№ Р Т‘Р В»РЎРЏ РЎРѓР С•Р Р†Р СР ВµРЎРѓРЎвЂљР С‘Р СР С•РЎРѓРЎвЂљР С‘ РЎРѓР С• РЎРѓРЎвЂљР В°РЎР‚РЎвЂ№Р С Р С”Р С•Р Т‘Р С•Р С
MarketData = MarketData
StrategyPort = BaseStrategy
Signal = Decision


class StrategyManager:
    """
    Р С’Р С–РЎР‚Р ВµР С–Р В°РЎвЂљР С•РЎР‚ РЎРѓРЎвЂљРЎР‚Р В°РЎвЂљР ВµР С–Р С‘Р в„–.
    Р СњР В° Р С—Р ВµРЎР‚Р Р†Р С•Р С РЎРЊРЎвЂљР В°Р С—Р Вµ РІР‚вЂќ Р С•Р Т‘Р С‘Р Р… РЎРѓР С‘Р С–Р Р…Р В°Р В» (EMA+ATR). Р СџР С•Р В·Р В¶Р Вµ Р СР С•Р В¶Р Р…Р С• Р Т‘Р С•Р В±Р В°Р Р†Р В»РЎРЏРЎвЂљРЎРЉ Р Т‘РЎР‚РЎС“Р С–Р С‘Р Вµ
    Р С‘ Р В°Р С–РЎР‚Р ВµР С–Р С‘РЎР‚Р С•Р Р†Р В°РЎвЂљРЎРЉ (Р Р†Р В·Р Р†Р ВµРЎв‚¬Р С‘Р Р†Р В°Р Р…Р С‘Р Вµ/Р С—РЎР‚Р С‘Р С•РЎР‚Р С‘РЎвЂљР ВµРЎвЂљРЎвЂ№).
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
        # Р СџРЎР‚Р С•РЎРѓРЎвЂљР С•Р в„– Р С—РЎР‚Р С‘Р С•РЎР‚Р С‘РЎвЂљР ВµРЎвЂљ: Р С—Р ВµРЎР‚Р Р†Р В°РЎРЏ, Р Т‘Р В°Р Р†РЎв‚¬Р В°РЎРЏ directional-РЎРѓР С‘Р С–Р Р…Р В°Р В»
        for strat in self._strategies:
            from crypto_ai_bot.core.domain.strategies.base_strategy import StrategyContext

            ctx = StrategyContext(symbol=symbol, settings=self._settings)
            sig = await strat.generate(md=self._md, ctx=ctx)
            if sig.action in ("buy", "sell"):
                return sig
        return Signal(action="hold", reason="all_hold")
