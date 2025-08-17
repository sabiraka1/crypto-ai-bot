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
    Простая эвристика на случай, если _build не задал rule_score.
    """
    ind = feat.get("indicators", {})
    ema_fast = _to_float(ind.get("ema_fast") or ind.get("ema20"))
    ema_slow = _to_float(ind.get("ema_slow") or ind.get("ema50"))
    rsi = _to_float(ind.get("rsi"), 50.0)
    macd_hist = _to_float(ind.get("macd_hist"))

    score = 0.5
    if ema_fast and ema_slow:
        score += 0.15 if ema_fast > ema_slow else -0.15
    score += (rsi - 50.0) / 200.0  # ±0.25 макс вклад
    if macd_hist:
        score += max(min(macd_hist, 1.0), -1.0) * 0.1
    return max(0.0, min(1.0, score))


def _sizing(cfg: Settings, action: str, feat: Dict[str, Any]) -> Decimal:
    if action == "hold":
        return Decimal("0")
    raw = getattr(cfg, "POSITION_SIZE", "0.00")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("0")


def _stops_takeprofit(cfg: Settings, feat: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
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

    return {"sl": to_dec(sl_pct), "tp": to_dec(tp_pct), "trail": to_dec(trail_pct)}


def decide(
    cfg: Settings,
    broker: Any,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """
    Единая точка принятия решений: build → fuse → risk → decision (+ расширенный explain).
    Учитывает профили решений из Settings (веса/пороги).
    """
    ts_ms = int(time.time() * 1000)

    # 1) features
    features = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    rule_score = features.get("rule_score")
    ai_score = features.get("ai_score")
    if rule_score is None:
        rule_score = _compute_rule_score(features)

    # 2) fuse (взвешивание rule/ai по профилю)
    w_rule, w_ai = cfg.get_weights()
    if hasattr(_fusion, "fuse"):
        score = float(_fusion.fuse(rule_score, ai_score, cfg))
    else:
        # fallback: простая взвешенная сумма
        r = _to_float(rule_score, 0.0)
        a = _to_float(ai_score, 0.0)
        score = max(0.0, min(1.0, w_rule * r + w_ai * a))

    # 3) risk checks
    ok, reason = risk_manager.check(features, cfg)

    # 4) thresholds/profile
    buy_thr, sell_thr = cfg.get_thresholds()
    if not ok:
        action = "hold"
    elif score >= buy_thr:
        action = "buy"
    elif score <= sell_thr:
        action = "sell"
    else:
        action = "hold"

    size = _sizing(cfg, action, features)
    stops = _stops_takeprofit(cfg, features)

    # 5) explain (развёрнутый)
    ind = features.get("indicators", {})
    market = features.get("market", {})
    profile = cfg.get_profile_dict()

    explain = {
        "signals": {
            "ema_fast": ind.get("ema_fast") or ind.get("ema20"),
            "ema_slow": ind.get("ema_slow") or ind.get("ema50"),
            "rsi": ind.get("rsi"),
            "macd_hist": ind.get("macd_hist"),
            "atr": ind.get("atr"),
            "atr_pct": ind.get("atr_pct"),
            "price": market.get("price"),
        },
        "blocks": ({reason: True} if not ok and reason else {}),
        "weights": profile["weights"],
        "thresholds": profile["thresholds"],
        "context": {
            "profile": profile["name"],
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
