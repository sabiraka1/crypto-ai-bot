# src/crypto_ai_bot/core/signals/policy.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics


def _heuristic_rule_score(features: Dict[str, Any]) -> float:
    ind = features.get("indicators", {})
    ema_f = ind.get("ema_fast")
    ema_s = ind.get("ema_slow")
    rsi = ind.get("rsi")
    macd_hist = ind.get("macd_hist")
    if None in (ema_f, ema_s, rsi, macd_hist):
        return 0.5
    score = 0.5
    score += 0.2 if ema_f > ema_s else -0.2
    if 45 <= rsi <= 60:
        score += 0.05
    elif rsi < 30 or rsi > 70:
        score -= 0.1
    score += 0.1 if macd_hist > 0 else -0.1
    return max(0.0, min(1.0, score))


def _position_size_buy(cfg, price: float) -> Decimal:
    quote_usd = Decimal(str(getattr(cfg, "ORDER_QUOTE_SIZE", "100")))
    if price <= 0:
        return Decimal("0")
    return (quote_usd / Decimal(str(price))).quantize(Decimal("0.00000001"))


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    if feats.get("rule_score") is None:
        feats["rule_score"] = _heuristic_rule_score(feats)

    score = _fusion.fuse(feats.get("rule_score"), feats.get("ai_score"), cfg)
    ok, reason = risk_manager.check(feats, cfg)

    price = float(feats["market"]["price"] or 0.0)
    atr_pct = float(feats["indicators"]["atr_pct"] or 0.0)

    BUY_TH = float(getattr(cfg, "SCORE_BUY_MIN", 0.6))
    SELL_TH = float(getattr(cfg, "SCORE_SELL_MIN", 0.4))
    SLx = float(getattr(cfg, "SL_ATR_MULT", 1.5))
    TPx = float(getattr(cfg, "TP_ATR_MULT", 2.5))

    explain = {
        "signals": {
            "ema_fast": feats["indicators"]["ema_fast"],
            "ema_slow": feats["indicators"]["ema_slow"],
            "rsi": feats["indicators"]["rsi"],
            "macd_hist": feats["indicators"]["macd_hist"],
            "atr_pct": atr_pct,
        },
        "blocks": {"risk_ok": ok, "risk_reason": reason},
        "weights": {
            "rule": float(getattr(cfg, "DECISION_RULE_WEIGHT", getattr(cfg, "SCORE_RULE_WEIGHT", 0.7))),
            "ai": float(getattr(cfg, "DECISION_AI_WEIGHT", getattr(cfg, "SCORE_AI_WEIGHT", 0.3))),
        },
        "thresholds": {"buy": BUY_TH, "sell": SELL_TH, "sl_atr": SLx, "tp_atr": TPx},
        "context": {"price": price, "timeframe": timeframe, "symbol": symbol},
        "rule_score": feats.get("rule_score"),
        "ai_score": feats.get("ai_score"),
    }

    decision: Dict[str, Any] = {
        "action": "hold",
        "size": "0",
        "sl": None,
        "tp": None,
        "trail": None,
        "score": score,
        "explain": explain,
    }

    if not ok:
        metrics.inc("decide_blocked_total", {"reason": reason})
        return decision

    if score >= BUY_TH and price > 0:
        size = _position_size_buy(cfg, price)
        sl = price * (1.0 - (SLx * atr_pct / 100.0)) if atr_pct > 0 else None
        tp = price * (1.0 + (TPx * atr_pct / 100.0)) if atr_pct > 0 else None
        decision.update({"action": "buy", "size": str(size), "sl": sl, "tp": tp})
    elif score <= SELL_TH and price > 0:
        frac = float(getattr(cfg, "SELL_SIGNAL_FRACTION", 0.5))
        decision.update({"action": "sell", "size": str(frac), "sl": None, "tp": None})

    metrics.inc("bot_decision_total", {"action": decision["action"]})
    return decision
