from __future__ import annotations

from typing import Dict, Any, Tuple
from dataclasses import dataclass

from crypto_ai_bot.core.signals import _build
from crypto_ai_bot.core.signals import _fusion  # if you have a separate fusion, otherwise inline combine
from crypto_ai_bot.utils.metrics import inc, observe

@dataclass
class Thresholds:
    buy: float
    sell: float

def _rule_score(feat: Dict[str, Any]) -> float:
    """Heuristic, normalized [0..1].

    + EMA fast above slow -> bullish

    + RSI 50..70 moderate bullish; <30 oversold (bullish contrarian), >70 overbought (bearish contrarian)

    + MACD hist > 0 bullish

    """
    ind = feat.get("indicators", {})
    ema_fast = float(ind.get("ema_fast", 0.0))
    ema_slow = float(ind.get("ema_slow", 0.0))
    rsi = float(ind.get("rsi", 50.0))
    macd_hist = float(ind.get("macd_hist", 0.0))

    score = 0.5  # neutral anchor
    # EMA cross
    if ema_fast > 0 and ema_slow > 0:
        score += 0.2 if ema_fast > ema_slow else -0.2
    # RSI
    if rsi >= 55 and rsi <= 70:
        score += 0.15
    elif rsi < 30:
        score += 0.10  # contrarian oversold
    elif rsi > 70:
        score -= 0.10  # contrarian overbought
    # MACD hist
    if macd_hist > 0:
        score += 0.15
    else:
        score -= 0.05
    # clamp
    return max(0.0, min(1.0, score))

def _combine_scores(rule_score: float | None, ai_score: float | None, cfg) -> float:
    if rule_score is None and ai_score is None:
        return 0.5
    if ai_score is None:
        return float(rule_score)
    if rule_score is None:
        return float(ai_score)
    # weighted
    w_rule = float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5))
    w_ai = float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5))
    s = w_rule + w_ai or 1.0
    w_rule, w_ai = w_rule/s, w_ai/s
    return float(max(0.0, min(1.0, w_rule*rule_score + w_ai*ai_score)))

def _action_from_score(score: float, thr: Thresholds) -> str:
    if score >= thr.buy:
        return "buy"
    if score <= thr.sell:
        return "sell"
    return "hold"

def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    f = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # rule score
    rs = _rule_score(f)
    f["rule_score"] = rs
    # ai_score остаётся None (можно подмешать позже из модели)
    final_score = _combine_scores(rs, f.get("ai_score"), cfg)

    thr = Thresholds(buy=float(getattr(cfg, "THRESHOLD_BUY", 0.6)),
                     sell=float(getattr(cfg, "THRESHOLD_SELL", 0.4)))
    action = _action_from_score(final_score, thr)

    # default size
    size = str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0"))

    explain = {
        "signals": f.get("indicators", {}),
        "blocks": {},  # заполнится risk-менеджером снаружи при отказах
        "weights": {
            "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
            "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5)),
        },
        "thresholds": {
            "buy": thr.buy,
            "sell": thr.sell,
        },
        "context": f.get("context", {}),
    }

    decision = {
        "id": "",  # может быть заполнен выше по конвейеру, если требуется
        "symbol": f.get("symbol"),
        "timeframe": f.get("timeframe"),
        "action": action,
        "size": size,
        "sl": None,
        "tp": None,
        "trail": None,
        "score": final_score,
        "explain": explain,
    }

    # metrics
    try:
        inc("bot_decision_total", {"action": action})
        observe("decision_score_histogram", final_score, {})
    except Exception:
        pass

    return decision
