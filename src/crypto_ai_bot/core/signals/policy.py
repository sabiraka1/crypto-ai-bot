from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.risk import manager as risk_manager
from . import _build, _fusion


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Единая точка принятия решений.
    1) build → features
    2) risk.check(features, cfg) → возможно HOLD
    3) fuse(rule_score, ai_score, cfg) → score
    4) policy → action/size/sl/tp/trail
    Возвращает dict (Decision-like) + explain.
    """
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    # Гарантируем базовые поля explain
    explain: Dict[str, Any] = {
        "signals": features.get("indicators", {}),
        "blocks": {},
        "weights": {
            "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
            "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5)),
        },
        "thresholds": {
            "buy": float(getattr(cfg, "THRESHOLD_BUY", 0.55)),
            "sell": float(getattr(cfg, "THRESHOLD_SELL", 0.45)),
        },
        "context": {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
        },
    }

    # Risk gate
    ok, reason = risk_manager.check(features, cfg)
    if not ok:
        explain["blocks"]["risk"] = reason
        return {
            "action": "hold",
            "size": "0",
            "sl": None,
            "tp": None,
            "trail": None,
            "score": 0.0,
            "explain": explain,
        }

    # Score fusion
    rule_score = features.get("rule_score")
    ai_score = features.get("ai_score")
    score = _fusion.fuse(rule_score, ai_score, cfg)

    # Простая политика на основе порогов
    th_buy = float(getattr(cfg, "THRESHOLD_BUY", 0.55))
    th_sell = float(getattr(cfg, "THRESHOLD_SELL", 0.45))
    if score >= th_buy:
        action, size = "buy", getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01")
    elif score <= th_sell:
        action, size = "sell", getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01")
    else:
        action, size = "hold", "0"

    decision = {
        "action": action,
        "size": str(size),
        "sl": None,
        "tp": None,
        "trail": None,
        "score": float(score),
        "explain": explain,
    }
    return decision
