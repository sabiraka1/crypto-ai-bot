# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations
from typing import Any, Dict

from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.utils.rate_ops import GLOBAL_RATE_LIMITER as _R

def _get(repo_container: Any, *names: str):
    for n in names:
        if hasattr(repo_container, n):
            return getattr(repo_container, n)
    return None

def eval_and_execute(*, cfg, broker, repos, symbol: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Совместимость со старым кодом: repos может иметь trades/positions
    или trades_repo/positions_repo и т.п.
    decision: {'side': 'buy'|'sell'}
    """
    trades_repo     = _get(repos, "trades_repo", "trades")
    positions_repo  = _get(repos, "positions_repo", "positions")
    exits_repo      = _get(repos, "exits_repo", "exits")
    idemp_repo      = _get(repos, "idempotency_repo", "idempotency")

    if trades_repo is None or positions_repo is None:
        return {"accepted": False, "error": "repos-missing"}

    side = (decision or {}).get("side")
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid-decision"}

    # === rate-limit на торговые действия по (symbol, side) ===
    lim_key = f"place_order:{symbol}:{side}"
    rps = float(getattr(cfg, "PLACE_ORDER_RPS", 1.0))
    burst = float(getattr(cfg, "PLACE_ORDER_BURST", 2.0))
    if not _R.allow(lim_key, rps=rps, burst=burst):
        return {"accepted": False, "error": "rate_limited"}

    return place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        symbol=symbol,
        side=side,
        idempotency_repo=idemp_repo,
    )

# старый псевдоним
def evaluate(*args, **kwargs):
    return eval_and_execute(*args, **kwargs)
