# src/crypto_ai_bot/core/signals/policy.py
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, Optional

from . import _build, _fusion
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.risk import manager as risk_manager


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _compute_rule_score(feat: Dict[str, Any]) -> float:
    """
    Небольшой, но стабильный эвристический скор, если _build не положил rule_score.
    Смотрим базовые сигналы: EMA-cross, RSI, MACD-hist.
    Возвращаем [0..1].
    """
    ind = feat.get("indicators", {})
    ema_fast = _to_float(ind.get("ema_fast") or ind.get("ema20"))
    ema_slow = _to_float(ind.get("ema_slow") or ind.get("ema50"))
    rsi = _to_float(ind.get("rsi"), 50.0)
    macd_hist = _to_float(ind.get("macd_hist"))

    score = 0.5
    if ema_fast and ema_slow:
        if ema_fast > ema_slow:
            score += 0.15
        elif ema_fast < ema_slow:
            score -= 0.15
    if rsi:
        # чем дальше от 50, тем сильнее вклад
        score += (rsi - 50.0) / 200.0  # ±0.25 максимум
    if macd_hist:
        score += max(min(macd_hist, 1.0), -1.0) * 0.1

    return max(0.0, min(1.0, score))


def _pick_thresholds(cfg: Settings) -> Dict[str, float]:
    buy = float(getattr(cfg, "DECISION_BUY_THRESHOLD", 0.55))
    sell = float(getattr(cfg, "DECISION_SELL_THRESHOLD", 0.45))
    return {"buy": buy, "sell": sell}


def _sizing(cfg: Settings, action: str, feat: Dict[str, Any]) -> Decimal:
    if action == "hold":
        return Decimal("0")
    # простая политика позиционирования
    raw = getattr(cfg, "POSITION_SIZE", "0.00")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("0")


def _stops_takeprofit(cfg: Settings, feat: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    ind = feat.get("indicators", {})
    atr_pct = feat.get("indicators", {}).get("atr_pct")
    sl_pct = getattr(cfg, "STOP_LOSS_PCT", None)
    tp_pct = getattr(cfg, "TAKE_PROFIT_PCT", None)
    trail_pct = getattr(cfg, "TRAILING_PCT", None)

    def to_dec(x):
        if x is None:
            return None
        try:
            return Decimal(str(x))
        except Exception:
            return None

    # если есть atr_pct и нет ручных настроек — возьмём от ATR
    if atr_pct and sl_pct is None:
        sl_pct = float(atr_pct) * 1.0  # 1×ATR
    return {
        "sl": to_dec(sl_pct),
        "tp": to_dec(tp_pct),
        "trail": to_dec(trail_pct),
    }


def decide(
    cfg: Settings,
    broker: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """
    Единственная публичная точка решений:
      - собираем фичи (_build)
      - склеиваем скор (_fusion)
      - проверяем риски
      - формируем Decision (+ подробный explain)
    """
    ts_ms = int(time.time() * 1000)

    # 1) фичи
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    rule_score = features.get("rule_score")
    ai_score = features.get("ai_score")

    if rule_score is None:
        rule_score = _compute_rule_score(features)

    # 2) склейка скорингов
    score = float(_fusion.fuse(rule_score, ai_score, cfg) if hasattr(_fusion, "fuse") else rule_score)

    # 3) риск-проверки
    ok, reason = risk_manager.check(features, cfg)

    # 4) пороги и экшен
    thr = _pick_thresholds(cfg)
    if not ok:
        action = "hold"
    elif score >= thr["buy"]:
        action = "buy"
    elif score <= thr["sell"]:
        action = "sell"
    else:
        action = "hold"

    size = _sizing(cfg, action, features)
    stops = _stops_takeprofit(cfg, features)

    # 5) подробный explain по спецификации
    ind = features.get("indicators", {})
    market = features.get("market", {})
    explain = {
        "signals": {
            # отдаём компактные, но полезные цифры
            "ema_fast": ind.get("ema_fast") or ind.get("ema20"),
            "ema_slow": ind.get("ema_slow") or ind.get("ema50"),
            "rsi": ind.get("rsi"),
            "macd_hist": ind.get("macd_hist"),
            "atr": ind.get("atr"),
            "atr_pct": ind.get("atr_pct"),
            "price": market.get("price"),
        },
        "blocks": ({reason: True} if not ok and reason else {}),
        "weights": {
            "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", getattr(cfg, "DECISION_RULE_WEIGHT", 0.5))),
            "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", getattr(cfg, "DECISION_AI_WEIGHT", 0.5))),
        },
        "thresholds": {
            "buy": thr["buy"],
            "sell": thr["sell"],
        },
        "context": {
            "mode": getattr(cfg, "MODE", "paper"),
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
            "ts_ms": ts_ms,
        },
    }

    decision = {
        "id": f"{symbol}:{timeframe}:{ts_ms}",
        "ts_ms": ts_ms,
        "action": action,
        "size": str(size),
        "sl": stops["sl"],
        "tp": stops["tp"],
        "trail": stops["trail"],
        "score": score,
        "explain": explain,
    }
    return decision
