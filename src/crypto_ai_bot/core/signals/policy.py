from __future__ import annotations

from typing import Dict, Any, Tuple
from decimal import Decimal

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils.time_sync import measure_time_drift

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _heuristic_rule_score(ind: Dict[str, float]) -> float:
    """
    Простая прозрачная эвристика: EMA cross + RSI + MACD hist.
    Даёт базовый rule_score ∈ [0..1], без учёта AI.
    """
    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 0.0)
    rsi = ind.get("rsi", 50.0)
    macd_hist = ind.get("macd_hist", 0.0)

    s = 0.5
    s += 0.2 if ema_fast > ema_slow else -0.2
    if rsi > 55.0:
        s += 0.15
    elif rsi < 45.0:
        s -= 0.15
    s += 0.05 if macd_hist > 0 else (-0.05 if macd_hist < 0 else 0.0)
    return _clamp01(s)


def _choose_action(score: float, cfg) -> str:
    buy_th = getattr(cfg, "BUY_THRESHOLD", 0.60)
    sell_th = getattr(cfg, "SELL_THRESHOLD", 0.40)
    if score >= buy_th:
        return "buy"
    if score <= sell_th:
        return "sell"
    return "hold"


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Единая точка принятия решений.
    1) Собираем features (_build)
    2) Подмешиваем time_drift_ms
    3) Risk check
    4) Считаем score (rule + AI через _fusion)
    5) Выбираем action + формируем explain
    """
    # 1) features
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    if "context" not in feats or not isinstance(feats["context"], dict):
        feats["context"] = {}

    # 2) time drift (безопасно: ошибки не валят пайплайн)
    drift_ms = None
    try:
        http = get_http_client()
        drift_ms = measure_time_drift(cfg=cfg, http=http)
    except Exception:
        drift_ms = None
    feats["context"]["time_drift_ms"] = drift_ms

    # 3) risk
    ok, reason = risk_manager.check(feats, cfg)
    risk_block = None if ok else reason

    # 4) scoring
    ind = feats.get("indicators", {}) if isinstance(feats, dict) else {}
    rule_score = _heuristic_rule_score(ind)
    feats["rule_score"] = rule_score

    ai_score = feats.get("ai_score")  # если где-то ранее подмешивается — поддержим
    score = _fusion.fuse(rule_score, ai_score, cfg)

    # 5) решение
    action = "hold" if not ok else _choose_action(score, cfg)
    size = Decimal("0")
    if action != "hold":
        # Можно использовать единый параметр позиции, если задан
        pos_sz = getattr(cfg, "DEFAULT_ORDER_SIZE", None) or getattr(cfg, "TRADE_SIZE", None)
        if pos_sz:
            size = Decimal(str(pos_sz))
        else:
            size = Decimal("0.0")  # по умолчанию не открываем без явного размера

    # SL/TP/Trail — опционально, если есть логика; пока оставим None
    decision = {
        "action": action,
        "size": str(size),
        "sl": None,
        "tp": None,
        "trail": None,
        "score": float(score),
        "explain": {
            "signals": ind,
            "blocks": {"risk": risk_block} if risk_block else {},
            "weights": {
                "rule": getattr(cfg, "SCORE_RULE_WEIGHT", 0.7),
                "ai": getattr(cfg, "SCORE_AI_WEIGHT", 0.3),
            },
            "thresholds": {
                "buy": getattr(cfg, "BUY_THRESHOLD", 0.60),
                "sell": getattr(cfg, "SELL_THRESHOLD", 0.40),
            },
            "context": {
                "bars": feats.get("context", {}).get("bars"),
                "time_drift_ms": drift_ms,
            },
        },
    }

    # метрики
    try:
        metrics.observe("decision_score", decision["score"], {"symbol": symbol, "tf": timeframe})
        metrics.inc("decision_total", {"action": action, "symbol": symbol, "tf": timeframe})
        if not ok:
            metrics.inc("decision_blocked_total", {"reason": risk_block or "unknown"})
    except Exception:
        pass

    return decision
