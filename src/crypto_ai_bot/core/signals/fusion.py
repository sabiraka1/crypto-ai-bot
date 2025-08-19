# src/crypto_ai_bot/core/signals/_fusion.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, TypedDict, NotRequired

from crypto_ai_bot.utils import metrics  # noqa: F401
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift_ms  # optional
except Exception:
    measure_time_drift_ms = None  # type: ignore

BUY_TH = 0.6
SELL_TH = -0.6

class Explain(TypedDict, total=False):
    source: NotRequired[str]
    reason: NotRequired[str]
    signals: Dict[str, float]
    contributions: Dict[str, float]
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    context: Dict[str, Any]

@dataclass
class Decision:
    action: str   # 'buy' | 'sell' | 'hold'
    score: float = 0.0
    reason: Optional[str] = None

def _weighted_sum(signals: Dict[str, float], weights: Optional[Dict[str, float]]) -> Tuple[float, Dict[str, float]]:
    score = 0.0
    contrib: Dict[str, float] = {}
    w = weights or {}
    for k, v in (signals or {}).items():
        w_k = float(w.get(k, 1.0))
        c = float(v) * w_k
        contrib[k] = c
        score += c
    return score, contrib

def decide(signals: Dict[str, float], ctx: Dict[str, Any]) -> Decision:
    if not signals:
        return Decision("hold", 0.0, "no_signals")
    weights = ctx.get("weights") or {}
    score, _ = _weighted_sum(signals, weights)
    buy_th = float(ctx.get("BUY_THRESHOLD", BUY_TH))
    sell_th = float(ctx.get("SELL_THRESHOLD", SELL_TH))
    if score >= buy_th:
        return Decision("buy", score, "score>=buy_th")
    if score <= sell_th:
        return Decision("sell", score, "score<=sell_th")
    return Decision("hold", score, "in_band")

def build(features: Dict[str, float], context: Dict[str, Any], cfg: Any) -> Dict[str, Any]:
    ctx = dict(context or {})
    drift_val = None
    if measure_time_drift_ms:
        try:
            timeout = float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0))
            drift_val = float(measure_time_drift_ms(timeout=timeout))  # type: ignore[arg-type]
        except Exception:
            try:
                metrics.inc("context_time_drift_errors_total")
            except Exception:
                pass
            drift_val = None
    ctx["time_drift_ms"] = drift_val
    ctx["now_ms"] = ctx.get("now_ms") or int(__import__("time").time() * 1000)
    return {"features": features or {}, "context": ctx}

def fuse_and_decide(features: Dict[str, float], cfg: Any, context: Optional[Dict[str, Any]] = None) -> Tuple[Decision, Dict[str, Any]]:
    built = build(features, context or {}, cfg)
    ctx = built["context"]
    dec = decide(built["features"], ctx)
    return dec, ctx

def explain(features: Dict[str, float], ctx: Dict[str, Any]) -> Explain:
    """Возвращает вклад сигналов и пороги, чтобы объяснить решение."""
    weights = ctx.get("weights") or {}
    score, contributions = _weighted_sum(features or {}, weights)
    return {
        "signals": dict(features or {}),
        "contributions": dict(sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)),
        "weights": dict(weights),
        "thresholds": {"buy": float(ctx.get("BUY_THRESHOLD", BUY_TH)), "sell": float(ctx.get("SELL_THRESHOLD", SELL_TH))},
        "context": {"time_drift_ms": ctx.get("time_drift_ms"), "now_ms": ctx.get("now_ms")},
    }

__all__ = ["Decision", "decide", "build", "fuse_and_decide", "explain"]
