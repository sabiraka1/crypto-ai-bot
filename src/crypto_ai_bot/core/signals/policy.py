from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils.metrics import inc, observe


def _thresholds(cfg) -> Dict[str, float]:
    """
    Единая точка конфигурации порогов.
    Если в Settings нет полей — берём безопасные дефолты.
    """
    return {
        "buy": float(getattr(cfg, "DECISION_BUY_THRESHOLD", 0.55)),
        "sell": float(getattr(cfg, "DECISION_SELL_THRESHOLD", 0.45)),
        "hold_band": float(getattr(cfg, "DECISION_HOLD_BAND", 0.04)),  # мёртвая зона вокруг 0.5
    }


def _weights(cfg) -> Dict[str, float]:
    # приведение имён к тому, что реально хранится в Settings
    rule_w = float(getattr(cfg, "SCORE_RULE_WEIGHT", getattr(cfg, "DECISION_RULE_WEIGHT", 0.5)))
    ai_w = float(getattr(cfg, "SCORE_AI_WEIGHT", getattr(cfg, "DECISION_AI_WEIGHT", 0.5)))
    s = rule_w + ai_w
    if s <= 0:
        rule_w, ai_w = 0.5, 0.5
    else:
        rule_w, ai_w = rule_w / s, ai_w / s
    return {"rule": rule_w, "ai": ai_w}


def _decide_action(score: float, th: Dict[str, float]) -> str:
    # вокруг 0.5 оставляем "hold"
    if abs(score - 0.5) <= th["hold_band"]:
        return "hold"
    if score >= th["buy"]:
        return "buy"
    if score <= th["sell"]:
        return "sell"
    return "hold"


def _size_from_cfg(cfg) -> Decimal:
    # базовый размер, без риска/мани-менеджмента
    raw = getattr(cfg, "DEFAULT_ORDER_SIZE", "0")
    try:
        return Decimal(str(raw))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    ЕДИНСТВЕННАЯ публичная точка принятия решений.
    Возвращает dict совместимый с Decision (action/size/sl/tp/trail/score/explain).
    """
    t0_build = _build.time_perf_counter()
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    observe("features_build_seconds", _build.time_perf_counter() - t0_build, {"symbol": symbol, "tf": timeframe})

    w = _weights(cfg)
    score = _fusion.fuse(features.get("rule_score"), features.get("ai_score"), cfg)
    th = _thresholds(cfg)

    # риск-правила
    ok, reason = risk_manager.check(features, cfg)
    blocks = {"risk": {"ok": bool(ok), "reason": reason}}

    action = "hold" if not ok else _decide_action(score, th)

    # базовые TP/SL — только если есть ATR
    sl = tp = trail = None
    if ok and action in ("buy", "sell"):
        atr = features.get("indicators", {}).get("atr")
        price = features.get("market", {}).get("price")
        if atr and price:
            atr = float(atr)
            mul_sl = float(getattr(cfg, "SL_ATR_MULT", 2.0))
            mul_tp = float(getattr(cfg, "TP_ATR_MULT", 3.0))
            if action == "buy":
                sl = Decimal(str(price - mul_sl * atr))
                tp = Decimal(str(price + mul_tp * atr))
            else:
                sl = Decimal(str(price + mul_sl * atr))
                tp = Decimal(str(price - mul_tp * atr))

    size = Decimal("0") if action == "hold" else _size_from_cfg(cfg)

    # explain — ПОЛНЫЙ формат
    explain = {
        "signals": features.get("indicators", {}),   # EMA/RSI/MACD/ATR и т.п.
        "blocks": blocks,                             # какие проверки сработали/заблокировали
        "weights": w,                                 # веса rule/ai
        "thresholds": th,                             # buy/sell/hold_band
        "context": {                                  # минимальный рыночный контекст
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
            "price": str(features.get("market", {}).get("price", "")),
        },
    }

    # метрики
    inc("bot_decision_total", {"action": action})
    observe("decision_score_histogram", float(score), {"symbol": symbol, "tf": timeframe})

    return {
        "action": action,
        "size": str(size),         # строкой — безопасно для JSON/Decimal
        "sl": str(sl) if sl is not None else None,
        "tp": str(tp) if tp is not None else None,
        "trail": str(trail) if trail is not None else None,
        "score": float(score),
        "explain": explain,
    }
