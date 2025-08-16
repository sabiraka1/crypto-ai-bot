from __future__ import annotations
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.risk import manager as risk_manager

def eval_and_execute(
    cfg,
    broker,
    *,
    symbol: Optional[str],
    timeframe: Optional[str],
    limit: Optional[int],
    positions_repo=None,
    trades_repo=None,
    audit_repo=None,
    uow=None,
    idempotency_repo=None,
) -> Dict[str, Any]:
    """Full cycle: evaluate → risk.check → (optional) execute with idempotency.
    Works even if repositories are None (evaluate-only).
    """
    decision = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    ok, reason = risk_manager.check(decision, cfg)
    if not ok:
        return {'status': 'blocked', 'reason': reason, 'decision': decision}

    enable = bool(getattr(cfg, 'ENABLE_TRADING', False))
    if not enable or not all([positions_repo, trades_repo, audit_repo, uow]):
        return {'status': 'evaluated', 'decision': decision, 'note': 'trading_disabled_or_no_storage'}

    exec_res = place_order(
        cfg,
        broker,
        positions_repo,
        trades_repo,
        audit_repo,
        uow,
        idempotency_repo,
        decision,
    )
    return {'status': exec_res.get('status'), 'decision': decision, 'exec': exec_res}
