from typing import Any, Callable
﻿from __future__ import annotations

from .base import BaseStrategy, MarketData, StrategyContext, Decision  # Добавлен Decision

# Подсистема signals (готовая, но ранее не включённая в рантайм)
try:
    from crypto_ai_bot.core.domain.signals._build import build_signals
    from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
    from crypto_ai_bot.core.domain.signals.policy import Policy as SignalsPolicy  # Исправлено имя
except Exception:  # если кто-то удалил подсистему
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
        self.score = 1.0  # для weighted-режима менеджера

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        if SignalsPolicy is None or fuse_signals is None or build_signals is None:
            return Decision(action="hold", reason="signals_subsystem_unavailable")

        # Упрощенная реализация без build_signals (так как он требует другие параметры)
        # Используем данные из MarketData напрямую
        ticker = await md.get_ticker(ctx.symbol)
        features = {
            "last": ticker.get("last", 0),
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "spread_pct": ((ticker.get("ask", 0) - ticker.get("bid", 0)) / ticker.get("last", 1)) * 100 if ticker.get("last", 0) > 0 else 0,
        }

        # Применяем политику
        policy = SignalsPolicy()
        decision, score, explain = policy(features) if callable(policy) else policy.decide(features)

        return Decision(action=decision, confidence=score, reason=str(explain or ""))
