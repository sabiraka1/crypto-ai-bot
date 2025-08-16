from __future__ import annotations

"""
core/signals/policy.py
Единая точка принятия решений. Строит features через _build, объединяет оценки через _fusion,
применяет risk-manager и возвращает Decision с полем explain в расширенном формате.
Правила (строго):
- никакого IO/HTTP/ENV; только переданные зависимости (cfg, broker)
- приватные помощники из _build/_fusion не экспортируем наружу
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from . import _build, _fusion

try:
    from crypto_ai_bot.core.risk.manager import check as risk_check  # type: ignore
except Exception:
    risk_check = None  # мягкий фолбэк


def _utc_minute_epoch(dt: Optional[datetime] = None) -> int:
    d = (dt or datetime.now(timezone.utc)).replace(second=0, microsecond=0, tzinfo=timezone.utc)
    return int(d.timestamp())


def _extract_signals(features: Dict[str, Any]) -> Dict[str, float]:
    """Нормализуем и отберём ключевые сигналы для explain."""
    sigs = {}
    ind = (features or {}).get("indicators") or {}
    for k in ("ema_fast", "ema_slow", "rsi", "macd", "macd_signal", "macd_hist", "atr", "atr_pct"):
        v = ind.get(k)
        try:
            sigs[k] = float(v) if v is not None else None  # type: ignore[assignment]
        except Exception:
            pass
    # market context (частично)
    mkt = (features or {}).get("market") or {}
    for k in ("price",):
        v = mkt.get(k)
        try:
            sigs[k] = float(v) if v is not None else None  # type: ignore[assignment]
        except Exception:
            pass
    return {k: v for k, v in sigs.items() if v is not None}


def _rule_score_from_features(features: Dict[str, Any]) -> Optional[float]:
    """Простейшая логика: EMA cross + RSI зоны. Используется только если _build не дал rule_score."""
    ind = (features or {}).get("indicators") or {}
    rsi = ind.get("rsi")
    ema_fast = ind.get("ema_fast")
    ema_slow = ind.get("ema_slow")
    macd_hist = ind.get("macd_hist")

    score_parts = []
    try:
        if ema_fast is not None and ema_slow is not None:
            score_parts.append(1.0 if float(ema_fast) > float(ema_slow) else 0.0)
    except Exception:
        pass
    try:
        if rsi is not None:
            r = float(rsi)
            # 30..70 neutral, >70 overheated, <30 oversold
            if r > 70:
                score_parts.append(0.25)  # осторожнее к покупкам
            elif r < 30:
                score_parts.append(0.75)
            else:
                score_parts.append(0.5)
    except Exception:
        pass
    try:
        if macd_hist is not None:
            mh = float(macd_hist)
            score_parts.append(0.5 + max(-0.5, min(0.5, mh / 100.0)))
    except Exception:
        pass

    if not score_parts:
        return None
    # усредним в [0..1]
    s = sum(score_parts) / len(score_parts)
    return float(max(0.0, min(1.0, s)))


def _weights(cfg) -> Dict[str, float]:
    rw = float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5) or 0.0)
    aw = float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5) or 0.0)
    if rw < 0: rw = 0.0
    if aw < 0: aw = 0.0
    if rw + aw == 0:
        rw = aw = 0.5
    # нормализуем
    s = rw + aw
    return {"rule": rw / s, "ai": aw / s}


def _thresholds(cfg) -> Dict[str, float]:
    b = float(getattr(cfg, "THRESHOLD_BUY", 0.55) or 0.55)
    s = float(getattr(cfg, "THRESHOLD_SELL", 0.45) or 0.45)
    # защита от некорректных конфигов
    if b <= s:
        b, s = 0.55, 0.45
    b = min(1.0, max(0.0, b))
    s = min(1.0, max(0.0, s))
    return {"buy": b, "sell": s}


def decide(
    cfg,
    broker,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Единая публичная функция принятия решения."""
    sym = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = timeframe or getattr(cfg, "TIMEFRAME", "1h")
    lim = int(limit or getattr(cfg, "DEFAULT_LIMIT", 300))

    # 1) Собираем features (_build сам валидирует OHLCV)
    feats = _build.build(cfg, broker, symbol=sym, timeframe=tf, limit=lim)

    # 2) Оценки (если _build дал rule_score/ai_score — используем)
    rule_score = feats.get("rule_score")
    ai_score = feats.get("ai_score")
    if rule_score is None:
        rule_score = _rule_score_from_features(feats)

    # 3) Слияние
    score = None
    try:
        score = _fusion.fuse(rule_score, ai_score, cfg)  # гарантирует [0..1]
    except Exception:
        # фолбэк на веса
        w = _weights(cfg)
        rs = float(rule_score) if rule_score is not None else 0.5
        ais = float(ai_score) if ai_score is not None else 0.5
        score = w["rule"] * rs + w["ai"] * ais
        score = max(0.0, min(1.0, float(score)))

    weights = _weights(cfg)
    thresholds = _thresholds(cfg)

    # 4) Риск-менеджер
    risk_ok, risk_reason = True, None
    if risk_check is not None:
        try:
            ok, reason = risk_check(feats, cfg)  # type: ignore[misc]
            risk_ok, risk_reason = bool(ok), (str(reason) if reason else None)
        except Exception as e:
            risk_ok, risk_reason = False, f"risk_failed:{type(e).__name__}"

    # 5) Решение
    action = "hold"
    if score >= thresholds["buy"]:
        action = "buy"
    elif score <= thresholds["sell"]:
        action = "sell"

    if not risk_ok:
        # блокируем торговлю, но показываем оценку
        action = "hold"

    # размер по умолчанию из настроек
    size = str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01") or "0.01")

    # 6) Соберём explain в расширенном формате
    explain = {
        "signals": _extract_signals(feats),
        "blocks": {} if risk_ok else {"risk": risk_reason or "blocked"},
        "weights": weights,
        "thresholds": thresholds,
        "context": {
            "mode": getattr(cfg, "MODE", "paper"),
            "symbol": sym,
            "timeframe": tf,
            "limit": lim,
            "ts_min": _utc_minute_epoch(),
            "id": f"why-{sym}-{tf}-{_utc_minute_epoch()}",
            "version": "v68",
        },
    }

    # 7) Собираем итоговый Decision
    decision = {
        "id": explain["context"]["id"],
        "symbol": sym,
        "timeframe": tf,
        "action": action,
        "size": size,
        "sl": None,
        "tp": None,
        "trail": None,
        "score": float(score),
        "explain": explain,
    }
    return decision
