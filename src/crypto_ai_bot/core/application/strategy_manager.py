from __future__ import annotations

from typing import Any, List

from crypto_ai_bot.core.domain.strategy.base import StrategyPort, MarketDataPort, Signal
from crypto_ai_bot.core.domain.strategy.strategies.ema_atr import EmaAtrStrategy, EmaAtrConfig
from crypto_ai_bot.utils.decimal import dec


class StrategyManager:
    """
    Агрегатор стратегий.
    На первом этапе — один сигнал (EMA+ATR). Позже можно добавлять другие
    и агрегировать (взвешивание/приоритеты).
    """

    def __init__(self, *, md: MarketDataPort, settings: Any) -> None:
        self._md = md
        self._settings = settings
        self._strategies: List[StrategyPort] = []
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
        # Простой приоритет: первая, давшая directional-сигнал
        for strat in self._strategies:
            sig = await strat.generate(symbol=symbol, md=self._md, settings=self._settings)
            if sig.action in ("buy", "sell"):
                return sig
        return Signal(action="hold", reason="all_hold")
