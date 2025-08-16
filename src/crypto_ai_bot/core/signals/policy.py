from __future__ import annotations

from typing import Any, Dict, Tuple, Optional
from decimal import Decimal

# приватные сборщики/фьюзер
from . import _build, _fusion

def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _rule_score(features: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Простая интерпретируемая rule-схема в [0..1], + разложение по компонентам.
    Использует RSI, EMA-кросс и знак MACD-гистограммы.
    """
    ind = (features.get("indicators") or {})
    ema_fast = _safe_float(ind.get("ema_fast"))
    ema_slow = _safe_float(ind.get("ema_slow"))
    rsi = _safe_float(ind.get("rsi"))
    macd_hist = _safe_float(ind.get("macd_hist"))

    parts: Dict[str, float] = {}

    # 1) RSI в коридоре [30..70]: 0.5 по центру, ближе к 70 — buy, ближе к 30 — sell
    if rsi <= 30:
        rsi_s = 0.0
    elif rsi >= 70:
        rsi_s = 1.0
    else:
        rsi_s = (rsi - 30.0) / 40.0  # 30→0.0; 70→1.0
    parts["rsi"] = rsi_s

    # 2) EMA-кросс: чем больше (ema_fast - ema_slow) относительно |ema_slow|, тем ближе к 1.0 (buy)
    cross_raw = 0.0
    if abs(ema_slow) > 1e-12:
        cross_raw = (ema_fast - ema_slow) / abs(ema_slow)
    cross_s = max(0.0, min(1.0, 0.5 + 2.0 * cross_raw))  # около 0.5 при равных EMA
    parts["ema_cross"] = cross_s

    # 3) MACD hist: >0 → buy bias, <0 → sell bias; нормируем симметрично
    macd_s = 0.5 + max(-0.5, min(0.5, macd_hist)) * 0.5  # мягкое сжатие
    parts["macd_hist"] = macd_s

    # усредняем части (равные веса внутри rule)
    rule_score = sum(parts.values()) / max(1, len(parts))
    return max(0.0, min(1.0, rule_score)), {"components": parts}

def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int, **repos) -> Dict[str, Any]:
    """
    Единая точка решений.
    Возвращает словарь с полями:
      - action: 'buy'|'sell'|'hold'
      - size: str|None
      - sl|tp|trail: Decimal|None (пока None — задаются на уровне исполнителя/стратегии)
      - score: float [0..1]
      - explain: {signals, blocks, weights, thresholds, context}
    """
    blocks: Dict[str, Any] = {}

    # 1) сбор фич
    try:
        feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
    except Exception as e:
        # если не удалось собрать фичи — удержание позиции с объяснением
        return {
            "symbol": symbol, "timeframe": timeframe,
            "action": "hold", "size": None, "sl": None, "tp": None, "trail": None,
            "score": 0.5,
            "explain": {
                "signals": {},
                "blocks": {"build_failed": f"{type(e).__name__}: {e}"},
                "weights": {"rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
                            "ai":   float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5))},
                "thresholds": {"buy": float(getattr(cfg, "THRESHOLD_BUY", 0.60)),
                               "sell": float(getattr(cfg, "THRESHOLD_SELL", 0.40))},
                "context": {},
            },
        }

    ind = feats.get("indicators") or {}
    market = feats.get("market") or {}

    # 2) rule score + разложение
    rule_s, rule_detail = _rule_score(feats)

    # 3) ai_score (если где-то посчитан заранее) — мягкая интеграция
    ai_s: Optional[float] = None
    if feats.get("ai_score") is not None:
        try:
            ai_s = float(feats["ai_score"])
        except Exception:
            ai_s = None

    # 4) объединяем rule + ai через фьюзер
    score = _fusion.fuse(rule_s, ai_s, cfg)
    score = max(0.0, min(1.0, float(score)))

    # 5) пороги и действие
    thr_buy = float(getattr(cfg, "THRESHOLD_BUY", 0.60))
    thr_sell = float(getattr(cfg, "THRESHOLD_SELL", 0.40))

    if score >= thr_buy:
        action = "buy"
    elif score <= thr_sell:
        action = "sell"
    else:
        action = "hold"

    # 6) собрать explain
    signals = {
        "ema_fast": ind.get("ema_fast"),
        "ema_slow": ind.get("ema_slow"),
        "rsi": ind.get("rsi"),
        "macd_hist": ind.get("macd_hist"),
        "atr": ind.get("atr"),
        "atr_pct": ind.get("atr_pct"),
        **(feats.get("signals") or {}),  # если билдер даёт доп. сигналы
    }

    context = {
        "price": market.get("price"),
        "ts": market.get("ts"),
        "spread_pct": market.get("spread_pct"),
        "vol": market.get("volume"),
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": limit,
    }

    explain = {
        "signals": signals,
        "blocks": blocks,
        "weights": {
            "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
            "ai":   float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5)),
        },
        "thresholds": {
            "buy": thr_buy,
            "sell": thr_sell,
        },
        "rule_detail": rule_detail,
        "context": context,
    }

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "action": action,
        "size": None,
        "sl": None,
        "tp": None,
        "trail": None,
        "score": score,
        "explain": explain,
    }
