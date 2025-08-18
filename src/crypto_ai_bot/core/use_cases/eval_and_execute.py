# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import RateLimitExceeded
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order

# Risk manager (мягкая зависимость: если не загрузится — просто пропустим проверки)
try:
    from crypto_ai_bot.core.risk.manager import RiskManager
except Exception:
    RiskManager = None  # type: ignore


def eval_and_execute(
    cfg: Any,
    broker: ExchangeInterface,
    repos: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    bus: Optional[Any] = None,
    http: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Сквозной flow:
      1) evaluate()
      2) risk manager (если доступен)
      3) place_order() при необходимости
    """
    # 1) Evaluate
    decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # быстрый выход при hold
    action = str(getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else "")).lower()
    if action in ("", "hold", None):
        return {"status": "hold", "decision": decision}

    # 2) Risk checks (если модуль доступен)
    if RiskManager is not None:
        try:
            rm = RiskManager(cfg, broker=broker, positions_repo=repos.positions, trades_repo=repos.trades, http=http)
            risk = rm.evaluate(symbol=symbol, action=action)
        except Exception as e:
            risk = {"ok": True, "error": f"{type(e).__name__}: {e}"}
    else:
        risk = {"ok": True, "error": "risk_manager_unavailable"}

    if not bool(risk.get("ok", True)):
        # публикуем событие в шину (если есть)
        if bus:
            try:
                bus.publish({
                    "type": "RiskBlocked",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "action": action,
                    "reasons": risk.get("blocked_by", []),
                    "details": risk.get("details", {}),
                })
            except Exception:
                pass
        return {
            "status": "blocked_by_risk",
            "decision": decision,
            "risk": risk,
        }

    # 3) Execute
    try:
        with metrics.timer() as t_order:
            result = place_order(
                cfg,
                broker,
                positions_repo=repos.positions,
                trades_repo=repos.trades,
                audit_repo=repos.audit,
                uow=repos.uow,
                decision=decision,
                symbol=symbol,
                bus=bus,
                idem_repo=repos.idempotency if hasattr(repos, "idempotency") else None,
            )
        metrics.observe_histogram("latency_order_seconds", t_order.elapsed)
        metrics.check_performance_budget("order_p99", t_order.elapsed, getattr(cfg, "PERF_BUDGET_ORDER_P99", None))
    except RateLimitExceeded as e:
        metrics.inc("rate_limit_exceeded_total", {"operation": "place_order"})
        return {"status": "rate_limited", "error": str(e), "decision": decision}

    return {"status": "ok", "decision": decision, "order": result, "risk": risk}
