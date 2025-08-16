from __future__ import annotations
from typing import Dict, Any, Optional

from . import _build, _fusion

# контекст добавляем по возможности (опционально)
try:
    from crypto_ai_bot.core.positions import tracker as _tracker
except Exception:
    _tracker = None  # мягкая зависимость

def _thresholds(cfg) -> Dict[str, float]:
    buy = float(getattr(cfg, "THRESHOLD_BUY", 0.60))
    sell = float(getattr(cfg, "THRESHOLD_SELL", 0.40))
    return {"buy": buy, "sell": sell}

def _weights(cfg) -> Dict[str, float]:
    # нормализуем на всякий случай
    rw = float(getattr(cfg, "SCORE_RULE_WEIGHT", getattr(cfg, "DECISION_RULE_WEIGHT", 0.5)))
    aw = float(getattr(cfg, "SCORE_AI_WEIGHT", getattr(cfg, "DECISION_AI_WEIGHT", 0.5)))
    s = rw + aw
    if s <= 0:
        rw, aw = 0.5, 0.5
    else:
        rw, aw = rw / s, aw / s
    return {"rule": rw, "ai": aw}

def _size_for_action(cfg, action: str) -> str:
    if action == "buy":
        return str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0.0"))
    if action == "sell":
        return str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0.0"))
    return "0"

def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int, **kwargs) -> Dict[str, Any]:
    """
    Единая точка принятия решения.
    Сбор фичей/индикаторов делегирован в _build. Слияние rule/ai — в _fusion.
    Здесь формируем публичное решение + explain.
    """
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    rule_score = feats.get("rule_score")
    ai_score = feats.get("ai_score")
    score = _fusion.fuse(rule_score, ai_score, cfg)

    thr = _thresholds(cfg)
    w = _weights(cfg)

    action: str
    if score >= thr["buy"]:
        action = "buy"
    elif score <= thr["sell"]:
        action = "sell"
    else:
        action = "hold"

    # базовое объяснение
    explain: Dict[str, Any] = {
        "signals": feats.get("indicators", {}),
        "thresholds": thr,
        "weights": w,
        "context": {},
    }

    # контекст: быстрый путь через трекер, если есть репозитории
    positions_repo = kwargs.get("positions_repo")
    trades_repo = kwargs.get("trades_repo")
    if _tracker is not None and (positions_repo is not None or trades_repo is not None):
        try:
            ctx = _tracker.build_context(cfg, broker, positions_repo=positions_repo, trades_repo=trades_repo)
            if isinstance(ctx, dict):
                explain["context"].update(ctx)
        except Exception:
            pass

    decision: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "action": action,
        "size": _size_for_action(cfg, action),
        "sl": None,
        "tp": None,
        "trail": None,
        "score": float(score) if score is not None else 0.0,
        "explain": explain,
    }
    return decision
