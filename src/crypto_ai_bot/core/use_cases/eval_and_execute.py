# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.risk.manager import RiskManager

if TYPE_CHECKING:
    # только для тайп-чекеров; в рантайме это не требуется
    from crypto_ai_bot.core.storage.repositories.interfaces import RepositoryInterfaces as _ReposT
else:
    _ReposT = Any


def eval_and_execute(
    cfg: Any,
    broker: Any,
    repos: _ReposT,  # <- используем интерфейсы (мягко)
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    bus: Optional[Any] = None,
    http: Optional[Any] = None,
) -> Dict[str, Any]:
    http = http or get_http_client()

    with metrics.timer() as t_dec:
        decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    metrics.observe_histogram("latency_decision_seconds", t_dec.elapsed, labels={"kind": "evaluate"})
    metrics.check_performance_budget("decision", t_dec.elapsed, getattr(cfg, "PERF_BUDGET_DECISION_P99_MS", None))

    action = (decision or {}).get("action", "hold")
    if str(action).lower() not in {"buy", "sell"}:
        return {
            "status": "no_action",
            "decision": decision,
            "risk": {"ok": True, "checks": {"skipped": True}, "blocks": []},
            "order": None,
        }

    rm = RiskManager(cfg, broker=broker, positions_repo=repos.positions, trades_repo=repos.trades, http=http)
    risk_rep = rm.evaluate(symbol=symbol, action=action)

    if not risk_rep.get("ok", False):
        for rule_code in risk_rep.get("blocks", []) or []:
            metrics.inc("risk_blocks_total", {"rule": str(rule_code)})
        return {"status": "blocked", "decision": decision, "risk": risk_rep, "order": None}

    with metrics.timer() as t_ord:
        order = place_order(cfg, broker, repos, decision=decision, symbol=symbol, bus=bus)
    metrics.observe_histogram("latency_order_seconds", t_ord.elapsed, labels={"kind": "place_order"})
    metrics.check_performance_budget("order", t_ord.elapsed, getattr(cfg, "PERF_BUDGET_ORDER_P99_MS", None))

    flow_elapsed = t_dec.elapsed + t_ord.elapsed
    metrics.observe_histogram("latency_flow_seconds", flow_elapsed, labels={"kind": "eval_and_execute"})
    metrics.check_performance_budget("flow", flow_elapsed, getattr(cfg, "PERF_BUDGET_FLOW_P99_MS", None))

    return {
        "status": "executed" if (order or {}).get("status") == "executed" else "ok",
        "decision": decision,
        "risk": risk_rep,
        "order": order,
    }
