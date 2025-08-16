from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone

from . import _build, _fusion

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

def _coalesce_rule_score(features: Dict[str, Any]) -> Optional[float]:
    # Если _build уже дал rule_score — используем его
    rs = features.get("rule_score")
    if isinstance(rs, (int, float)):
        try:
            x = float(rs)
            if x < 0: x = 0.0
            if x > 1: x = 1.0
            return x
        except Exception:
            pass
    # Простейшая эвристика fallback на основе индикаторов
    ind = features.get("indicators", {}) or {}
    ema_fast = ind.get("ema_fast") or ind.get("ema20") or ind.get("ema_20")
    ema_slow = ind.get("ema_slow") or ind.get("ema50") or ind.get("ema_50")
    rsi = ind.get("rsi")
    macd_hist = ind.get("macd_hist")
    score = 0.5
    try:
        if ema_fast is not None and ema_slow is not None:
            score += 0.2 if float(ema_fast) > float(ema_slow) else -0.2
    except Exception:
        pass
    try:
        if rsi is not None:
            r = float(rsi)
            if r < 30: score += 0.1
            if r > 70: score -= 0.1
    except Exception:
        pass
    try:
        if macd_hist is not None:
            mh = float(macd_hist)
            score += 0.1 if mh > 0 else -0.1
    except Exception:
        pass
    # clamp
    if score < 0: score = 0.0
    if score > 1: score = 1.0
    return score

def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int = 300, **repos) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решений.
    1) Собирает фичи через _build.build()
    2) Объединяет rule_score + ai_score → score через _fusion.fuse()
    3) Возвращает решение: action|size|sl|tp|trail|score + explain{signals,weights,thresholds,context}
    """
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)

    # Сигнальная часть (без IO): соединение rule/ai
    rule_score = _coalesce_rule_score(features)
    ai_score = features.get("ai_score")
    try:
        ai_score = float(ai_score) if ai_score is not None else None
    except Exception:
        ai_score = None

    score = _fusion.fuse(rule_score, ai_score, cfg)

    thr_buy = float(getattr(cfg, "THRESHOLD_BUY", 0.60))
    thr_sell = float(getattr(cfg, "THRESHOLD_SELL", 0.40))

    if score >= thr_buy:
        action = "buy"
    elif score <= thr_sell:
        action = "sell"
    else:
        action = "hold"

    # Размер/SL/TP/Trail — упрощённо: ответственность других слоёв/настроек
    size = "0"  # подбирается risk/position sizing, тут — не лезем
    sl = None
    tp = None
    trail = None

    decision: Dict[str, Any] = {
        "action": action,
        "size": size,
        "sl": sl,
        "tp": tp,
        "trail": trail,
        "score": float(score),
    }

    # --- explain ---
    ex = _ensure_explain(decision)

    # 1) signals — вытащим ключевые индикаторы из features (если есть)
    ind = features.get("indicators", {}) or {}
    # аккуратно приводим к float где возможно
    def _maybe_float(x):
        try:
            return float(x)
        except Exception:
            return x
    ex["signals"].update({
        "ema_fast": _maybe_float(ind.get("ema_fast", ind.get("ema20", ind.get("ema_20")))),
        "ema_slow": _maybe_float(ind.get("ema_slow", ind.get("ema50", ind.get("ema_50")))),
        "rsi": _maybe_float(ind.get("rsi")),
        "macd_hist": _maybe_float(ind.get("macd_hist")),
        "atr": _maybe_float(ind.get("atr")),
        "atr_pct": _maybe_float(ind.get("atr_pct")),
    })

    # 2) weights
    ex["weights"].update({
        "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
        "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5)),
    })

    # 3) thresholds
    ex["thresholds"].update({
        "buy": thr_buy,
        "sell": thr_sell,
    })

    # 4) context: symbol/timeframe/price/ts/mode
    price = None
    ts = None
    mkt = features.get("market", {})
    if isinstance(mkt, dict):
        price = mkt.get("price")
        ts = mkt.get("ts")
    ex["context"].update({
        "symbol": symbol,
        "timeframe": timeframe,
        "price": _maybe_float(price),
        "ts": ts if ts is not None else datetime.now(timezone.utc).isoformat(),
        "mode": getattr(cfg, "MODE", "paper"),
    })

    return decision
