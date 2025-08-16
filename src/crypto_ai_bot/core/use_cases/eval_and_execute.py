# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.utils import metrics
from .evaluate import evaluate
from .place_order import place_order


def eval_and_execute(
    cfg,
    broker,
    con,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """
    Полный конвейер: evaluate → (при необходимости) execute.
    Риск-менеджмент уже учтён в policy.decide (через core.risk.manager).
    """
    dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    action = str(dec.get("action", "hold")).lower()
    if action == "hold":
        return {"decision": dec, "order": {"status": "skipped", "reason": "hold"}}

    res = place_order(cfg, broker, con, dec)
    metrics.inc("pipeline_runs_total", {"result": str(res.get("status"))})
    return {"decision": dec, "order": res}
