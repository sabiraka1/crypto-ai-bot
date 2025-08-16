from __future__ import annotations
from typing import Any, Dict, Optional
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics

def eval_and_execute(
    cfg,
    broker,
    *,
    idem_repo,
    trades_repo=None,
    audit_repo=None,
    positions_repo=None,
    symbol: Optional[str]=None,
    timeframe: Optional[str]=None,
    limit: Optional[int]=None,
) -> Dict[str, Any]:
    dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    # риск
    ok, reason = risk_manager.check(dec.get("explain",{}), cfg)  # features здесь могут быть расширены
    if not ok:
        return {"status":"blocked","reason":reason,"decision":dec}
    if dec.get("action") not in ("buy","sell"):
        return {"status":"skipped","decision":dec}

    res = place_order(cfg, broker, decision=dec, idem_repo=idemp_repo, trades_repo=trades_repo, audit_repo=audit_repo, positions_repo=positions_repo)
    metrics.inc("eval_execute_total", {"status": res.get("status","unknown")})
    return {"status":"executed","result":res,"decision":dec}
