# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils import metrics

# корректный модуль декоратора
try:
    from crypto_ai_bot.utils.rate_limit import rate_limit
except Exception:
    def rate_limit(*_, **__):
        def _wrap(fn):
            return fn
        return _wrap

_HIST_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000)

def _observe_hist(name: str, value_ms: int, labels: Optional[Dict[str, str]] = None) -> None:
    lbls = dict(labels or {})
    for b in _HIST_BUCKETS_MS:
        if value_ms <= b:
            metrics.inc(f"{name}_bucket", {**lbls, "le": str(b)})
    metrics.inc(f"{name}_bucket", {**lbls, "le": "+Inf"})
    metrics.observe(f"{name}_sum", value_ms, lbls)
    metrics.inc(f"{name}_count", lbls)


@rate_limit(limit=60, per=60)  # ≤ 60 evaluate/мин
def evaluate(
    cfg: Settings,
    broker: Any,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME
    lim = int(limit or getattr(cfg, "LIMIT_BARS", 300))

    t0 = time.perf_counter()
    decision = policy.decide(cfg, broker, symbol=sym, timeframe=tf, limit=lim)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    metrics.inc("bot_decision_total", {"action": str(decision.get("action", "unknown"))})
    metrics.observe("latency_decide_ms", latency_ms, {"symbol": sym, "timeframe": tf})
    _observe_hist("latency_decide_ms", latency_ms, {"symbol": sym, "timeframe": tf})

    if bus is not None:
        try:
            bus.publish(
                {
                    "type": "DecisionEvaluated",
                    "symbol": sym,
                    "timeframe": tf,
                    "score": decision.get("score"),
                    "action": decision.get("action"),
                    "size": str(decision.get("size", "0")),
                    "explain": decision.get("explain"),
                    "latency_ms": latency_ms,
                }
            )
        except Exception:
            pass

    try:
        json.dumps(decision, default=str)
    except Exception:
        decision = json.loads(json.dumps(decision, default=str))

    return decision
