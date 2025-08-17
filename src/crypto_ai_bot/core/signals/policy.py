from __future__ import annotations

from typing import Any, Dict, Tuple
from decimal import Decimal

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager

# time drift
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:
    def measure_time_drift(urls=None, timeout: float = 1.5) -> Dict[str, Any]:
        return {"drift_ms": 0, "limit_ms": 0, "sources": [], "status": "unknown"}


def _weights(cfg) -> Tuple[float, float]:
    """
    Гибко читаем веса из настроек:
    - DECISION_RULE_WEIGHT / DECISION_AI_WEIGHT
    - или SCORE_RULE_WEIGHT / SCORE_AI_WEIGHT
    Нормализуем до суммы = 1.0
    """
    rw = getattr(cfg, "DECISION_RULE_WEIGHT", None)
    aw = getattr(cfg, "DECISION_AI_WEIGHT", None)
    if rw is None or aw is None:
        rw = getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)
        aw = getattr(cfg, "SCORE_AI_WEIGHT", 0.5)

    try:
        rw = float(rw)
        aw = float(aw)
    except Exception:
        rw, aw = 0.5, 0.5

    s = rw + aw
    if s <= 0:
        return 0.5, 0.5
    return rw / s, aw / s


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решений.
    Возвращает dict с полями: action, size, sl, tp, trail, score, explain{signals,weights,blocks,context}
    """
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # веса
    rw, aw = _weights(cfg)

    # расчёт rule/ai score → общий score
    rule_score = features.get("rule_score")
    ai_score = features.get("ai_score")
    score = _fusion.fuse(rule_score, ai_score, cfg)

    explain = {
        "signals": features.get("indicators") or {},
        "weights": {"rule": rw, "ai": aw},
        "blocks": {},
        "thresholds": {},
        "context": features.get("market") or {},
    }

    # --- Блок 1: time drift (жёсткая блокировка) ---
    try:
        drift = measure_time_drift(urls=getattr(cfg, "TIME_DRIFT_URLS", []) or None, timeout=1.5)
        drift_ms = int(drift.get("drift_ms", 0))
        limit_ms = int(drift.get("limit_ms", getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000)))
        explain["context"]["time_drift_ms"] = drift_ms
        explain["thresholds"]["time_drift_limit_ms"] = limit_ms
        if drift_ms > limit_ms:
            explain["blocks"]["time_drift"] = False
            return {
                "action": "hold",
                "size": "0",
                "sl": None,
                "tp": None,
                "trail": None,
                "score": 0.0,
                "explain": explain,
            }
        else:
            explain["blocks"]["time_drift"] = True
    except Exception:
        # если измерение не удалось — не блокируем, но помечаем неизвестность
        explain["blocks"]["time_drift"] = True

    # --- Блок 2: risk manager ---
    ok, reason = risk_manager.check(features, cfg)
    explain["blocks"]["risk"] = bool(ok)
    if not ok:
        return {
            "action": "hold",
            "size": "0",
            "sl": None,
            "tp": None,
            "trail": None,
            "score": float(score) if score is not None else 0.0,
            "explain": explain,
        }

    # --- Выставление параметров сделки (пример) ---
    # Здесь можно использовать индикаторы/ATR для расчёта sl/tp/trailing.
    sl = None
    tp = None
    trail = None

    # Пример: если score > 0.55 — buy; < 0.45 — sell; иначе hold
    act = "hold"
    if score is not None:
        if score >= 0.55:
            act = "buy"
        elif score <= 0.45:
            act = "sell"

    size = "0"
    if act in ("buy", "sell"):
        default_size = getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01")
        size = str(default_size)

    return {
        "action": act,
        "size": size,
        "sl": sl,
        "tp": tp,
        "trail": trail,
        "score": float(score) if score is not None else 0.0,
        "explain": explain,
    }
