# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

import time
from typing import Any, Dict

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils import metrics


def evaluate(cfg: Any, broker: Any, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Вычислить торговое решение без исполнения ордера.
    Единственная точка: вызывает core.signals.policy.decide(...)
    """
    t0 = time.perf_counter()
    decision = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    metrics.observe("latency_decide_seconds", time.perf_counter() - t0, {"tf": timeframe})
    metrics.inc("bot_decision_total", {"action": decision.get("action", "unknown")})
    return decision
