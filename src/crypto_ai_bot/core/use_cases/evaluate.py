from __future__ import annotations

import time
from typing import Any, Dict, Optional

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils import rate_limit as rl

def _ensure_explain(decision: Dict[str, Any]) -> Dict[str, Any]:
    ex = decision.get("explain")
    if not isinstance(ex, dict):
        ex = {}
        decision["explain"] = ex
    ex.setdefault("signals", {})
    ex.setdefault("blocks", {})
    ex.setdefault("weights", {})
    ex.setdefault("thresholds", {})
    ex.setdefault("context", {})
    return ex

def evaluate(cfg, broker, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300, risk_reason: Optional[str] = None, **repos) -> Dict[str, Any]:
    """
    Вычисляет торговое решение (без исполнения).
    В начале применяет rate limit по ключу eval:<symbol>:<timeframe>.
    При превышении — возвращает hold + explain.blocks.rate_limit (прозрачность).
    """
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME

    # --- rate limit ---
    calls = int(getattr(cfg, "RL_EVALUATE_CALLS", 6))
    per_s = float(getattr(cfg, "RL_EVALUATE_PERIOD_S", 10))
    key = f"eval:{sym}:{tf}"
    if not rl.allow(key, calls, per_s):
        decision = {
            "action": "hold",
            "size": "0",
            "sl": None,
            "tp": None,
            "trail": None,
            "score": 0.0,
            "symbol": sym,
            "timeframe": tf,
        }
        ex = _ensure_explain(decision)
        ex["blocks"]["rate_limit"] = {"key": key, "calls": calls, "per_s": per_s}
        if risk_reason:
            ex["blocks"]["risk"] = {"reason": str(risk_reason)}
        return decision

    # --- измерим latency decide ---
    t0 = time.perf_counter()
    decision = policy.decide(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)
    dt_ms = int((time.perf_counter() - t0) * 1000)
    try:
        metrics.observe("evaluate_latency_ms", dt_ms, {"symbol": sym, "tf": tf})
    except Exception:
        pass

    decision.setdefault("symbol", sym)
    decision.setdefault("timeframe", tf)

    if risk_reason:
        ex = _ensure_explain(decision)
        ex["blocks"]["risk"] = {"reason": str(risk_reason)}

    return decision
