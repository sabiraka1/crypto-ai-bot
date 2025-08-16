from __future__ import annotations
from typing import Any, Dict, Optional

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.core.use_cases.place_order import place_order

def eval_and_execute(
    cfg,
    broker,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    positions_repo=None,
    trades_repo=None,
    audit_repo=None,
    uow=None,
    idempotency_repo=None,
) -> Dict[str, Any]:
    decision = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    ok, reason = risk_manager.check(decision if isinstance(decision, dict) else {}, cfg)
    if not ok:
        return {"status": "blocked", "reason": reason, "decision": decision}
    res = place_order(
        cfg, broker,
        positions_repo=positions_repo, trades_repo=trades_repo, audit_repo=audit_repo, uow=uow, idempotency_repo=idempotency_repo,
        decision=decision if isinstance(decision, dict) else dict(decision),
    )
    return res
