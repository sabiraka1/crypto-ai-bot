from __future__ import annotations

from time import perf_counter
from typing import Any, Dict

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.utils.metrics import observe


def eval_and_execute(
    cfg: Any,
    broker: Any,
    repos: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """
    Конвейер: evaluate → (при необходимости) execute.
    Замеряем:
      - общую латентность eval_and_execute
      - латентность блока исполнения (place_order), если был вызван.
    """
    t_all = perf_counter()
    try:
        decision = uc_evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

        action = (decision.get("action") or "hold").lower()
        if action in ("buy", "reduce", "close"):
            t_exec = perf_counter()
            try:
                # ожидается, что repos имеет атрибуты: positions, trades, audit, uow
                result = uc_place_order(
                    cfg,
                    broker,
                    repos.positions,
                    repos.trades,
                    repos.audit,
                    repos.uow,
                    decision,
                )
                return {
                    "status": "executed",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "decision": decision,
                    "order": result,
                }
            finally:
                observe("uc_place_order_latency_seconds", perf_counter() - t_exec)
        else:
            return {
                "status": "evaluated",
                "symbol": symbol,
                "timeframe": timeframe,
                "decision": decision,
            }
    finally:
        observe("uc_eval_and_execute_latency_seconds", perf_counter() - t_all)
