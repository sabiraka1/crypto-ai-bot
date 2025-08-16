from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.utils import metrics

def eval_and_execute(cfg, broker, *, symbol: str, timeframe: str, limit: int, **repos) -> Dict[str, Any]:
    dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
    action = dec.get("action")
    if action in (None, "hold"):
        return {"status": "evaluated", "decision": dec}

    positions_repo = repos.get("positions_repo")
    audit_repo = repos.get("audit_repo")
    idem_repo = repos.get("idem_repo")

    res = place_order(cfg, broker, positions_repo, audit_repo, dec, idem_repo=idem_repo)
    metrics.inc("eval_and_execute_total", {"status": res.get("status", "unknown")})
    return {"status": "executed", "decision": dec, "order": res}
