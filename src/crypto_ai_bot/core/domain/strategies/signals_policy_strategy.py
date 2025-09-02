from __future__ import annotations
from typing import TYPE_CHECKING
from .base import BaseStrategy, MarketData, StrategyContext, Decision

# Подсистема signals (готовая, но ранее не включённая в рантайм)
if TYPE_CHECKING:
    from crypto_ai_bot.core.domain.signals._build import build_signals
    from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
    from crypto_ai_bot.core.domain.signals.policy import Policy as SignalsPolicy
else:
    try:
        from crypto_ai_bot.core.domain.signals._build import build_signals
        from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
        from crypto_ai_bot.core.domain.signals.policy import Policy as SignalsPolicy
    except ImportError:
        SignalsPolicy = None
        fuse_signals = None
        build_signals = None


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
        # Проверяем что модули были импортированы
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

        # Создаем экземпляр политики
        try:
            policy = SignalsPolicy()
            if hasattr(policy, 'decide'):
                decision, score, explain = policy.decide(features)
            else:
                # Если метода decide нет, возвращаем hold
                return Decision(action="hold", reason="policy_decide_not_found")
        except Exception as e:
            return Decision(action="hold", reason=f"policy_error:{e}")

        return Decision(action=decision, confidence=score, reason=str(explain or ""))