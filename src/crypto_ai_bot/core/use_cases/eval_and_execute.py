from __future__ import annotations

from time import perf_counter
from typing import Any, Dict

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.utils.metrics import observe, inc


def _persist_decision_if_possible(repos: Any, symbol: str, timeframe: str, decision: Dict[str, Any]) -> None:
    """
    Мягкая попытка сохранить решение в БД.
    Ничего не ломаем, если репозитория нет.
    """
    try:
        if hasattr(repos, "decisions") and repos.decisions:
            rowid = repos.decisions.insert(symbol=symbol, timeframe=timeframe, decision=decision)
            inc("decisions_saved_total", {"status": "ok"})
        else:
            inc("decisions_saved_total", {"status": "skipped"})
    except Exception:
        inc("decisions_saved_total", {"status": "error"})


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
    Конвейер: evaluate → (персист решения) → (при необходимости) execute.
    Замеряем:
      - общую латентность eval_and_execute
      - латентность блока исполнения (place_order), если был вызван.
    """
    t_all = perf_counter()
    try:
        decision = uc_evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

        # сохраняем решение (если есть репозиторий)
        _persist_decision_if_possible(repos, symbol, timeframe, decision)

        action = (decision.get("action") or "hold").lower()
        if action in ("buy", "reduce", "close"):
            t_exec = perf_counter()
            try:
                # ожидается, что repos имеет атрибуты: positions, trades, audit, uow (+ decisions необязателен)
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
