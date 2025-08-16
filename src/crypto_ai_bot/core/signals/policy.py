from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics

def _d(v, default: str = "0") -> str:
    try:
        return str(Decimal(str(v)))
    except Exception:
        return default

def _cfg(cfg, name: str, default):
    return getattr(cfg, name, default)

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

def _choose_action(score: float, buy_th: float, sell_th: float) -> str:
    if score >= buy_th:
        return "buy"
    if score <= sell_th:
        return "sell"
    return "hold"

def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int, **repos) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решения.
    Возвращает dict (Decision-подобный):
      {action, size, sl, tp, trail, score, explain{signals,blocks,weights,thresholds,context}}
    """
    # Сбор фич (OHLCV -> индикаторы -> normalize)
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
    ind = feats.get("indicators", {}) or {}
    market = feats.get("market", {}) or {}

    # Правила риска (блокировки)
    ok, reason = risk_manager.check(feats, cfg)

    # Rule/AI score (поддерживаем оба источника)
    rule_score = feats.get("rule_score")
    ai_score = feats.get("ai_score")
    score = float(_fusion.fuse(rule_score, ai_score, cfg))

    # Весовые коэффициенты/пороги из Settings
    w_rule = float(_cfg(cfg, "SCORE_RULE_WEIGHT", 0.5))
    w_ai   = float(_cfg(cfg, "SCORE_AI_WEIGHT", 0.5))
    th_buy  = float(_cfg(cfg, "BUY_THRESHOLD", 0.6))
    th_sell = float(_cfg(cfg, "SELL_THRESHOLD", 0.4))

    action = _choose_action(score, th_buy, th_sell)
    size = _d(_cfg(cfg, "ORDER_SIZE", "0"))

    # ATR-driven SL/TP/Trail (если есть atr/price)
    atr = ind.get("atr") or ind.get("atr_pct")
    price = market.get("price")
    sl = tp = trail = None
    if isinstance(price, (int, float)) and isinstance(atr, (int, float)):
        atr_mult_sl = float(_cfg(cfg, "SL_ATR_MULT", 0.0))
        atr_mult_tp = float(_cfg(cfg, "TP_ATR_MULT", 0.0))
        atr_mult_tr = float(_cfg(cfg, "TRAIL_ATR_MULT", 0.0))
        if atr_mult_sl > 0:
            sl = float(price - atr * atr_mult_sl) if action == "buy" else float(price + atr * atr_mult_sl)
        if atr_mult_tp > 0:
            tp = float(price + atr * atr_mult_tp) if action == "buy" else float(price - atr * atr_mult_tp)
        if atr_mult_tr > 0:
            trail = float(atr * atr_mult_tr)

    # Если риск заблокировал — держим позицию
    if not ok:
        action = "hold"

    # explain (полный формат)
    decision: Dict[str, Any] = {
        "action": action,
        "size": size if action in ("buy", "sell") else "0",
        "sl": sl,
        "tp": tp,
        "trail": trail,
        "score": score,
        "symbol": symbol,
        "timeframe": timeframe,
    }
    ex = _ensure_explain(decision)
    # signals — основные индикаторы, если есть
    for key in ("ema_fast", "ema_slow", "ema20", "ema50", "rsi", "macd", "macd_signal", "macd_hist", "atr", "atr_pct"):
        if key in ind:
            ex["signals"][key] = float(ind[key])
    # blocks — причина риска, если была
    if not ok:
        ex["blocks"]["risk"] = {"reason": str(reason)}
    # weights/thresholds
    ex["weights"] = {"rule": w_rule, "ai": w_ai}
    ex["thresholds"] = {"buy": th_buy, "sell": th_sell}
    # context — цена/время/лимит
    for ctx_k in ("price", "ts"):
        if ctx_k in market:
            try:
                ex["context"][ctx_k] = market[ctx_k]
            except Exception:
                pass
    ex["context"]["limit"] = int(limit)

    # метрики — гистограмма по score
    try:
        metrics.observe("decision_score", float(score), {"action": action}, buckets=[0.0, 0.25, 0.5, 0.75, 1.0])
    except Exception:
        pass

    return decision
