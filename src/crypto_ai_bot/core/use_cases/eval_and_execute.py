# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import RateLimitExceeded
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order

# Risk manager (мягкая зависимость)
try:
    from crypto_ai_bot.core.risk.manager import RiskManager
except Exception:
    RiskManager = None  # type: ignore

# IDs для трассировки
try:
    from crypto_ai_bot.utils.logging import get_correlation_id, get_request_id
except Exception:
    def get_correlation_id(): return None  # type: ignore
    def get_request_id(): return None      # type: ignore

# time drift (мягкая зависимость)
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:
    def measure_time_drift(cfg=None, http=None, *, urls=None, timeout: float = 1.5): return None  # type: ignore

log = logging.getLogger(__name__)


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
    decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    action = str(getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else "")).lower()
    if action in ("", "hold", None):
        # обогащаем explain.context даже для hold
        _enrich_decision_context(decision, cfg, repos, http)
        return {"status": "hold", "decision": decision}

    # risk checks
    if RiskManager is not None:
        try:
            rm = RiskManager(cfg, broker=broker, positions_repo=repos.positions, trades_repo=repos.trades, http=http)
            risk = rm.evaluate(symbol=symbol, action=action)
        except Exception as e:
            log.warning("risk_manager_failed: %s", e)
            metrics.inc("risk_manager_errors_total")
            risk = {"ok": True, "error": f"{type(e).__name__}: {e}"}
    else:
        risk = {"ok": True, "error": "risk_manager_unavailable"}

    if not bool(risk.get("ok", True)):
        if bus:
            try:
                bus.publish({
                    "type": "RiskBlocked",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "action": action,
                    "reasons": risk.get("blocked_by", []),
                    "details": risk.get("details", {}),
                    "request_id": get_request_id(),
                    "correlation_id": get_correlation_id(),
                })
            except Exception as e:
                log.warning("bus_publish_failed (RiskBlocked): %s", e)
                metrics.inc("bus_publish_errors_total")
        _enrich_decision_context(decision, cfg, repos, http)
        return {"status": "blocked_by_risk", "decision": decision, "risk": risk}

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
        metrics.check_performance_budget("order_p99", t_order.elapsed, getattr(cfg, "PERF_BUDGET_ORDER_P99_MS", None))
    except RateLimitExceeded as e:
        metrics.inc("rate_limit_exceeded_total", {"operation": "place_order"})
        _enrich_decision_context(decision, cfg, repos, http)
        return {"status": "rate_limited", "error": str(e), "decision": decision}
    except Exception as e:
        log.exception("place_order_failed: %s", e)
        metrics.inc("place_order_errors_total")
        _enrich_decision_context(decision, cfg, repos, http)
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "decision": decision}

    _enrich_decision_context(decision, cfg, repos, http)
    return {"status": "ok", "decision": decision, "order": result, "risk": risk}


# ------- helpers -------

def _enrich_decision_context(decision: Dict[str, Any], cfg: Any, repos: Any, http: Optional[Any]) -> None:
    """Добавляет в explain.context: exposure (кол-во открытых) и time_drift_ms."""
    try:
        exp = decision.get("explain", {})
        if not isinstance(exp, dict):
            return
        ctx = exp.get("context", {}) if isinstance(exp.get("context"), dict) else {}

        # exposure
        try:
            open_cnt = len(repos.positions.get_open() or [])
        except Exception:
            open_cnt = None

        # time drift
        try:
            td = measure_time_drift(cfg, http, urls=getattr(cfg, "TIME_DRIFT_URLS", None), timeout=1.5)
        except Exception:
            td = None

        ctx["exposure_open_positions"] = open_cnt
        ctx["time_drift_ms"] = td
        exp["context"] = ctx
        decision["explain"] = exp
    except Exception as e:
        log.debug("context_enrich_skip: %s", e)
