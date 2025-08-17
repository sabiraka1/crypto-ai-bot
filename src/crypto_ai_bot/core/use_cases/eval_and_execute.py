from __future__ import annotations

from typing import Any, Dict
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import RateLimitExceeded  # для аккуратной обработки
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order

def eval_and_execute(cfg: Any, broker: ExchangeInterface, repos: Any, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Сквозной flow:
      1) evaluate()
      2) risk manager + позиции (внутри place_order)
      3) place_order() при необходимости

    Централизованные гистограммы через utils.metrics.
    """
    # evaluate
    decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # быстрый выход при hold
    action = getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else None)
    if str(action) == "hold":
        return {"status": "hold", "decision": decision}

    # execute
    result: Dict[str, Any]
    try:
        with metrics.timer() as t_order:
            result = place_order(cfg, broker, repos, decision=decision, idempotency_key=None)
        metrics.observe_histogram("latency_order_seconds", t_order.elapsed)
        metrics.check_performance_budget("order_p99", t_order.elapsed, getattr(cfg, "PERF_BUDGET_ORDER_P99", None))
    except RateLimitExceeded as e:
        metrics.inc("rate_limit_exceeded_total", {"operation": "place_order"})
        return {"status": "rate_limited", "error": str(e), "decision": decision}
    return {"status": "ok", "decision": decision, "order": result}
