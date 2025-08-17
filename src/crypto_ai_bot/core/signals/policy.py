from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe
from crypto_ai_bot.utils.metrics import inc, observe

# Внутренний буфер последнего решения (память процесса)
_LAST_DECISION: Optional[Dict[str, Any]] = None


def _weights_from_cfg(cfg: Any) -> Tuple[float, float]:
    """
    Достаём веса rule/ai из настроек, поддерживаем оба варианта имён.
    """
    rule_w = float(getattr(cfg, "DECISION_RULE_WEIGHT", getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)))
    ai_w = float(getattr(cfg, "DECISION_AI_WEIGHT", getattr(cfg, "SCORE_AI_WEIGHT", 0.5)))
    # нормализуем на всякий случай
    s = rule_w + ai_w
    if s <= 0:
        return 1.0, 0.0
    return rule_w / s, ai_w / s


def _thresholds_from_cfg(cfg: Any) -> Dict[str, float]:
    """
    Пороговые значения, с безопасными дефолтами.
    """
    return {
        "entry_min": float(getattr(cfg, "ENTRY_SCORE_MIN", 0.60)),
        "exit_max": float(getattr(cfg, "EXIT_SCORE_MAX", 0.40)),
        "reduce_below": float(getattr(cfg, "REDUCE_SCORE_BELOW", 0.45)),
    }


def _format_decimal(x: Optional[Decimal]) -> Optional[str]:
    if x is None:
        return None
    # Читаемо и стабильно
    return f"{x:.8f}".rstrip("0").rstrip(".") if "." in f"{x:.8f}" else f"{x:.8f}"


def _fallback_rule_score(ind: Dict[str, float]) -> float:
    """
    Если _build не вернул rule_score, считаем простой эвристикой:
    - EMA fast/slow + RSI (55↔45 коридор)
    """
    ema_fast = float(ind.get("ema_fast", 0.0))
    ema_slow = float(ind.get("ema_slow", 0.0))
    rsi = float(ind.get("rsi", 50.0))

    base = 0.5
    if ema_fast > ema_slow:
        base += 0.1
    else:
        base -= 0.1

    if rsi >= 55:
        base += 0.05
    elif rsi <= 45:
        base -= 0.05

    return max(0.0, min(1.0, base))


def _make_explain(
    *,
    features: Dict[str, Any],
    rule_score: Optional[float],
    ai_score: Optional[float],
    fused_score: float,
    weights: Tuple[float, float],
    thresholds: Dict[str, float],
    risk_ok: bool,
    risk_reason: Optional[str],
    sym: str,
    tf: str,
    cfg: Any,
) -> Dict[str, Any]:
    ind = dict(features.get("indicators", {}))
    market = dict(features.get("market", {}))

    # signals — подробности сигналов/фич
    signals = {
        "ema_fast": ind.get("ema_fast"),
        "ema_slow": ind.get("ema_slow"),
        "rsi": ind.get("rsi"),
        "macd": ind.get("macd"),
        "macd_signal": ind.get("macd_signal"),
        "macd_hist": ind.get("macd_hist"),
        "atr": ind.get("atr"),
        "atr_pct": ind.get("atr_pct"),
        "price": float(market.get("price")) if market.get("price") is not None else None,
    }

    # blocks — кто/что блокировал или мог блокировать
    blocks = {
        "risk": None if risk_ok else (risk_reason or "blocked_by_risk_rules"),
        "data": None if ind else "no_indicators",
    }

    # weights — какие веса реально использовались при fusion
    weights_dict = {
        "rule": weights[0],
        "ai": weights[1],
    }

    # thresholds — пороги принятия решения
    thresholds_dict = dict(thresholds)

    # context — полезный контекст для /why
    context = {
        "symbol": sym,
        "timeframe": tf,
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if getattr(cfg, "PAPER_MODE", True) is False else "paper",
        "rule_score": rule_score,
        "ai_score": ai_score,
        "fused": fused_score,
    }

    return {
        "signals": signals,
        "blocks": blocks,
        "weights": weights_dict,
        "thresholds": thresholds_dict,
        "context": context,
    }


def _store_last(decision: Dict[str, Any]) -> None:
    global _LAST_DECISION
    _LAST_DECISION = decision


def get_last_decision() -> Optional[Dict[str, Any]]:
    """
    Возвращает последнее принятое решение за текущий процесс (если было).
    """
    return _LAST_DECISION


def decide(cfg: Any, broker: Any, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решений.
    Возвращает dict совместимый с Decision: {action,size,sl,tp,trail,score,explain}
    """
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)

    # Сбор/валидация/индикаторы
    try:
        features = _build.build(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
    except Exception as e:
        inc("decide_errors_total", {"stage": "build"})
        # fail-safe
        decision = {
            "action": "hold",
            "size": "0",
            "sl": None,
            "tp": None,
            "trail": None,
            "score": 0.0,
            "explain": {
                "signals": {},
                "blocks": {"data": f"build_failed:{type(e).__name__}"},
                "weights": {"rule": 1.0, "ai": 0.0},
                "thresholds": _thresholds_from_cfg(cfg),
                "context": {
                    "symbol": sym,
                    "timeframe": tf,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "mode": "live" if getattr(cfg, "PAPER_MODE", True) is False else "paper",
                    "rule_score": None,
                    "ai_score": None,
                    "fused": 0.0,
                },
            },
        }
        _store_last(decision)
        return decision

    ind = dict(features.get("indicators", {}))
    market = dict(features.get("market", {}))

    # rule/ai scores
    rule_score: Optional[float] = features.get("rule_score")
    if rule_score is None:
        rule_score = _fallback_rule_score(ind)

    ai_score: Optional[float] = features.get("ai_score")  # если есть модель — сюда

    # fusion
    fused = _fusion.fuse(rule_score, ai_score, cfg)  # 0..1
    observe("decision_score_histogram", fused)

    # risk-checks
    ok, reason = risk_manager.check(features, cfg)

    weights = _weights_from_cfg(cfg)
    thresholds = _thresholds_from_cfg(cfg)

    # упрощённая политика:
    action = "hold"
    size = Decimal("0")
    sl = None
    tp = None
    trail = None

    # если риск блокирует — только hold
    if ok:
        if fused >= thresholds["entry_min"]:
            action = "buy"
            # размер позиции может считаться сложнее; оставим "0" до интеграции позиционного sizing
            size = Decimal("0")
        elif fused <= thresholds["exit_max"]:
            action = "close"
            size = Decimal("0")
        else:
            # возможно частичное сокращение (reduce)
            if fused < thresholds["reduce_below"]:
                action = "reduce"
                size = Decimal("0")

    explain = _make_explain(
        features=features,
        rule_score=rule_score,
        ai_score=ai_score,
        fused_score=fused,
        weights=weights,
        thresholds=thresholds,
        risk_ok=ok,
        risk_reason=reason,
        sym=sym,
        tf=tf,
        cfg=cfg,
    )

    decision = {
        "action": action,
        "size": _format_decimal(size) or "0",
        "sl": _format_decimal(sl),
        "tp": _format_decimal(tp),
        "trail": _format_decimal(trail),
        "score": fused,
        "explain": explain,
    }

    _store_last(decision)
    return decision
