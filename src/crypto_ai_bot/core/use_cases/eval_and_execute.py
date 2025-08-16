# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.utils import metrics
from .evaluate import evaluate
from .place_order import place_order
from crypto_ai_bot.core.storage.interfaces import (
    TradeRepository,
    PositionRepository,
    AuditRepository,
    IdempotencyRepository,
)


def eval_and_execute(
    cfg,
    broker,
    con,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    trades: TradeRepository,
    positions: PositionRepository,
    audit: AuditRepository,
    idem: IdempotencyRepository | None = None,
) -> Dict[str, Any]:
    """
    Полный цикл: evaluate → (если не HOLD) place_order, с идемпотентностью.
    """
    dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    action = str(dec.get("action", "hold")).lower()
    if action == "hold":
        return {"decision": dec, "order": {"status": "skipped", "reason": "hold"}}

    res = place_order(
        cfg, broker, con, dec,
        trades=trades, positions=positions, audit=audit, idem=idem
    )
    metrics.inc("pipeline_runs_total", {"result": str(res.get("status"))})
    return {"decision": dec, "order": res}
