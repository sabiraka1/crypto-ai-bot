# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

from typing import Any, Dict
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.signals.policy import decide
from crypto_ai_bot.core.signals._build import build  # приватный билд фич

@rate_limit(max_calls=60, window=60)  # спецификация
def evaluate(cfg: Any, broker: ExchangeInterface, *, symbol: str, timeframe: str, limit: int) -> Any:
    symbol_n = normalize_symbol(symbol)
    timeframe_n = normalize_timeframe(timeframe)

    with metrics.timer() as t:
        features: Dict[str, Any] = build(cfg, broker, symbol=symbol_n, timeframe=timeframe_n, limit=int(limit))
        decision = decide(cfg, features)

    metrics.observe_histogram("latency_decide_seconds", t.elapsed)
    try:
        score = float(getattr(decision, "score", None) or decision.get("score"))
    except Exception:
        score = None
    if score is not None:
        metrics.observe_histogram("decision_score_histogram", max(0.0, min(1.0, score)))

    action = getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else "unknown")
    metrics.inc("bot_decision_total", {"action": str(action)})
    metrics.check_performance_budget("decide_p99", t.elapsed, getattr(cfg, "PERF_BUDGET_DECIDE_P99", None))

    return decision
