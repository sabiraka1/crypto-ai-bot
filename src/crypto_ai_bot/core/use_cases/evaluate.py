from __future__ import annotations

from time import perf_counter
from typing import Any, Dict

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils.metrics import inc, observe


def evaluate(
    cfg: Any,
    broker: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """
    Вычисляет решение (Decision) без исполнения.
    Замеряем латентность, инкрементим счётчики по action.
    """
    t0 = perf_counter()
    try:
        decision = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
        inc("bot_decision_total", {"action": decision.get("action", "hold")})
        return decision
    finally:
        observe("uc_evaluate_latency_seconds", perf_counter() - t0)
