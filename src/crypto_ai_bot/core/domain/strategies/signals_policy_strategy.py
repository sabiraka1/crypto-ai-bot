# src/crypto_ai_bot/core/domain/strategies/signals_policy_strategy.py
from __future__ import annotations

from typing import Any, Tuple

from .base import BaseStrategy, StrategyContext, MarketData

# Подсистема signals (готовая, но ранее не включённая в рантайм)
try:
    from crypto_ai_bot.core.domain.signals.policy import SignalsPolicy
    from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
    from crypto_ai_bot.core.domain.signals._build import build_signals
except Exception as e:  # если кто-то удалил подсистему
    SignalsPolicy = None  # type: ignore
    fuse_signals = None   # type: ignore
    build_signals = None  # type: ignore


class SignalsPolicyStrategy(BaseStrategy):
    """
    Адаптер, который:
      1) строит список сигналов из MarketData (build_signals)
      2) агрегирует их (fuse_signals)
      3) принимает решение по заданной политике (SignalsPolicy)
    """

    def __init__(self, *, policy: str = "conservative") -> None:
        self.policy_name = policy
        # Внутри SignalsPolicy можно реализовать набор правил, например:
        #  - conservative: нужна конвергенция ≥ K сигналов для buy/sell
        #  - aggressive: достаточно сильного одного/двух
        # Здесь мы не навязываем реализацию — используем то, что уже в модуле.
        self.score = 1.0  # для weighted-режима менеджера

    async def decide(self, *, ctx: StrategyContext, md: MarketData) -> Tuple[str, str]:
        if not (SignalsPolicy and fuse_signals and build_signals):
            return "hold", "signals_subsystem_unavailable"

        # 1) построить набор сигналов (из md)
        sigs = build_signals(md=md, mode=ctx.mode)

        # 2) агрегировать (например, нормировать/взвесить)
        fused = fuse_signals(sigs)

        # 3) применить политику
        policy = SignalsPolicy(name=self.policy_name)
        decision, explain = policy.decide(fused, ctx=ctx, md=md)

        # ожидается ('buy'|'sell'|'hold', explain:str)
        if decision not in ("buy", "sell", "hold"):
            return "hold", "signals_invalid_decision"
        return decision, str(explain or "")
