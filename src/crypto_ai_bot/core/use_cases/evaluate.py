from __future__ import annotations
from typing import Any, Dict

from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.use_cases.decide import evaluate_only
from crypto_ai_bot.utils.rate_limit import MultiLimiter

# Глобальный лимитер торговых действий (per (symbol, side))
_GLOBAL_RL = MultiLimiter({
    "place_order": {"rps": float(1.0), "burst": float(2.0)}
})

def eval_and_execute(*, cfg, broker, repos, symbol: str) -> Dict[str, Any]:
    """
    Back-compat точка: оцени, затем при необходимости исполни.
    """
    eval_res = evaluate_only(cfg=cfg, broker=broker, symbol=symbol)
    action = eval_res.get("action")
    if action not in ("buy", "sell"):
        return {"accepted": False, "decision": eval_res}

    # rate limiting поверх бизнес-операции
    key = f"place_order:{symbol}:{action}"
    if not _GLOBAL_RL.allow("place_order"):  # общий ключ; внутр. бакет учитывает rps/burst
        return {"accepted": False, "error": "rate_limited", "decision": eval_res}

    trades_repo     = getattr(repos, "trades_repo", getattr(repos, "trades", None))
    positions_repo  = getattr(repos, "positions_repo", getattr(repos, "positions", None))
    exits_repo      = getattr(repos, "exits_repo", getattr(repos, "exits", None))
    idemp_repo      = getattr(repos, "idempotency_repo", getattr(repos, "idempotency", None))

    if trades_repo is None or positions_repo is None:
        return {"accepted": False, "error": "repos_missing", "decision": eval_res}

    res = place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        symbol=symbol,
        side=action,
        idempotency_repo=idemp_repo,
    )
    res["decision"] = eval_res
    return res

# Старый псевдоним 'evaluate' (некоторые места могли вызывать)
def evaluate(*args, **kwargs):
    return eval_and_execute(*args, **kwargs)
