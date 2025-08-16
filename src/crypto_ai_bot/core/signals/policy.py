# src/crypto_ai_bot/core/signals/policy.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from . import _fusion
from . import _build
from crypto_ai_bot.core.risk import manager as risk_manager


@dataclass
class Decision:
    action: str            # "buy" | "sell" | "hold"
    score: float           # 0..1
    symbol: str
    timeframe: str
    size: Decimal = Decimal("0")
    sl: Optional[Decimal] = None
    tp: Optional[Decimal] = None
    trail: Optional[Decimal] = None
    explain: Dict[str, Any] | None = None

    def asdict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Decimal → str для транспорта
        for k in ("size", "sl", "tp", "trail"):
            if d[k] is not None:
                d[k] = str(d[k])
        return d


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _rule_score_from_indicators(ind: Dict[str, float], cfg) -> float:
    """
    Пример простого «правилового» скорера (детерминированный и объяснимый).
    Комбинируем несколько признаков: EMA тренд, RSI зоны, MACD импульс, ATR%.
    Возвращаем значение в [0..1].
    """
    ema20 = ind.get("ema20")
    ema50 = ind.get("ema50")
    rsi14 = ind.get("rsi14")
    macd_hist = ind.get("macd_hist")
    atr_pct = ind.get("atr_pct")

    parts: Dict[str, float] = {}

    # 1) Тренд: EMA20 vs EMA50
    if ema20 is not None and ema50 is not None:
        # нормированный тренд в -1..+1
        trend = 0.0
        if ema50 != 0:
            trend = (ema20 - ema50) / abs(ema50)
        # маппинг в [0..1]
        parts["trend"] = _clip01(0.5 + 3.0 * trend)  # усиление чувствительности
    else:
        parts["trend"] = 0.5

    # 2) RSI: 30..70 зона — нейтрально; выше — бычий, ниже — медвежий
    if rsi14 is not None:
        if rsi14 >= 70:
            parts["rsi"] = 0.8
        elif rsi14 <= 30:
            parts["rsi"] = 0.2
        else:
            # линейная интерполяция в зоне 30..70 вокруг 0.5
            parts["rsi"] = 0.5 + (rsi14 - 50.0) / 100.0
            parts["rsi"] = _clip01(parts["rsi"])
    else:
        parts["rsi"] = 0.5

    # 3) MACD histogram: знак и величина
    if macd_hist is not None:
        # ограничим до разумного диапазона
        mh = max(-1.0, min(1.0, macd_hist))
        parts["macd"] = _clip01(0.5 + 0.5 * mh)
    else:
        parts["macd"] = 0.5

    # 4) Волатильность (ATR%): очень высокая вола → чуть снижаем уверенность
    if atr_pct is not None:
        # выше этого порога начинаем penalize
        atr_soft = float(getattr(cfg, "ATR_PCT_SOFT_CAP", 3.0))
        if atr_pct <= atr_soft:
            parts["atr"] = 0.5
        else:
            # чем выше ATR%, тем ниже скор, но не ниже 0.3
            penalty = min(0.2, (atr_pct - atr_soft) * 0.01)
            parts["atr"] = max(0.3, 0.5 - penalty)
    else:
        parts["atr"] = 0.5

    # Веса правил
    w_trend = float(getattr(cfg, "RULE_TREND_WEIGHT", 0.35))
    w_rsi = float(getattr(cfg, "RULE_RSI_WEIGHT", 0.25))
    w_macd = float(getattr(cfg, "RULE_MACD_WEIGHT", 0.30))
    w_atr = float(getattr(cfg, "RULE_ATR_WEIGHT", 0.10))
    s = w_trend + w_rsi + w_macd + w_atr
    if s <= 0:
        w_trend, w_rsi, w_macd, w_atr = 0.35, 0.25, 0.30, 0.10
        s = 1.0
    w_trend /= s; w_rsi /= s; w_macd /= s; w_atr /= s

    score = (
        w_trend * parts["trend"]
        + w_rsi * parts["rsi"]
        + w_macd * parts["macd"]
        + w_atr * parts["atr"]
    )
    return _clip01(score)


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решений.
    Возвращает dict формата Decision.asdict(), включающий explain-поле с разбором.
    """
    # 1) Строим фичи (OHLCV → индикаторы)
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    ind = feats.get("indicators") or {}
    mkt = feats.get("market") or {}

    # 2) Правиловый скор
    rule_score = _rule_score_from_indicators(ind, cfg)

    # 3) AI-скор (если есть) — оставляем None по умолчанию
    ai_score = feats.get("ai_score")

    # 4) Слияние скорингов
    final_score = _fusion.fuse(rule_score, ai_score, cfg)

    # 5) Риски
    ok, reason = risk_manager.check(feats, cfg)

    # 6) Пороговые решения
    buy_th = float(getattr(cfg, "BUY_THRESHOLD", 0.60))
    sell_th = float(getattr(cfg, "SELL_THRESHOLD", 0.40))
    action = "hold"
    if ok:
        if final_score >= buy_th:
            action = "buy"
        elif final_score <= sell_th:
            action = "sell"
    else:
        action = "hold"

    # 7) Размер, SL/TP (минимальные дефолты — чтобы не ломать существующие обработчики)
    size = Decimal(str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0")))
    sl = None
    tp = None
    trail = None

    # 8) Объяснение
    explain = {
        "market": {
            "symbol": mkt.get("symbol"),
            "timeframe": mkt.get("timeframe"),
            "ts": str(mkt.get("ts")),
            "price": str(mkt.get("price")),
        },
        "indicators": {
            "ema20": ind.get("ema20"),
            "ema50": ind.get("ema50"),
            "rsi14": ind.get("rsi14"),
            "macd_hist": ind.get("macd_hist"),
            "atr": ind.get("atr"),
            "atr_pct": ind.get("atr_pct"),
        },
        "scores": {
            "rule_score": float(rule_score),
            "ai_score": None if ai_score is None else float(ai_score),
            "final": float(final_score),
            "weights": {
                "rule": float(getattr(cfg, "DECISION_RULE_WEIGHT", 0.7)),
                "ai": float(getattr(cfg, "DECISION_AI_WEIGHT", 0.3)),
            },
            "thresholds": {
                "buy": buy_th,
                "sell": sell_th,
            },
        },
        "risk": {
            "ok": bool(ok),
            "reason": reason,
        },
        "policy": {
            "action": action,
            "notes": "rule-based with ATR penalty; AI optional",
        },
    }

    metrics.observe("decision_score", float(final_score), {"symbol": mkt.get("symbol", "n/a")})
    if action == "buy":
        metrics.inc("decision_action_total", {"action": "buy"})
    elif action == "sell":
        metrics.inc("decision_action_total", {"action": "sell"})
    else:
        metrics.inc("decision_action_total", {"action": "hold"})

    return Decision(
        action=action,
        score=float(final_score),
        symbol=mkt.get("symbol") or symbol,
        timeframe=mkt.get("timeframe") or timeframe,
        size=size,
        sl=sl, tp=tp, trail=trail,
        explain=explain,
    ).asdict()
