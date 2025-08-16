# src/crypto_ai_bot/core/signals/policy.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils import metrics


def _heuristic_rule_score(features: Dict[str, Any]) -> float:
    """
    Простая эвристика: EMA-cross + RSI + MACD hist.
    Возвращает score в [0..1].
    """
    ind = features.get("indicators", {})
    ema_f = ind.get("ema_fast")
    ema_s = ind.get("ema_slow")
    rsi = ind.get("rsi")
    macd_hist = ind.get("macd_hist")

    if None in (ema_f, ema_s, rsi, macd_hist):
        return 0.5  # неопределённость → «нейтрально»

    score = 0.5
    # EMA cross
    if ema_f > ema_s:
        score += 0.2
    else:
        score -= 0.2
    # RSI зона
    if 45 <= rsi <= 60:
        score += 0.05
    elif rsi < 30:
        score -= 0.1
    elif rsi > 70:
        score -= 0.1
    # MACD hist знак
    if macd_hist > 0:
        score += 0.1
    else:
        score -= 0.1

    # зажать в [0..1]
    return max(0.0, min(1.0, score))


def _position_size_buy(cfg, price: float) -> Decimal:
    """
    Рассчитать размер покупки по квоте: ORDER_QUOTE_SIZE (в котируемой валюте).
    """
    quote_usd = Decimal(str(getattr(cfg, "ORDER_QUOTE_SIZE", "100")))
    if price <= 0:
        return Decimal("0")
    amt = quote_usd / Decimal(str(price))
    # округление по количеству знаков можно добавить при необходимости
    return amt


def _position_size_sell(cfg, broker, symbol: str) -> Decimal:
    """
    Продажа доли от базового баланса: SELL_BASE_FRACTION.
    """
    frac = Decimal(str(getattr(cfg, "SELL_BASE_FRACTION", "0.5")))
    # баланс берётся через брокера (если доступно), иначе продаём 0
    try:
        bal = broker.fetch_balance()
        # heuristic: выбрать «базовую» валюту по символу недоступно здесь без split,
        # поэтому продаём «самую крупную не-quote» мы не делаем. Доверимся use-case/позициям,
        # а здесь вернём 0 если неизвестно.
        # Если хочешь, могу расширить контракт и передавать сюда base.
        return Decimal("0") if not bal else Decimal("0")
    except Exception:
        return Decimal("0")


def decide(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    ЕДИНАЯ точка принятия решений.
    1) строим фичи
    2) считаем rule_score (если не задан в features)
    3) fuse(rule_score, ai_score)
    4) risk.check → ok? → генерим решение
    """
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)

    # rule_score: если не подан внешне — посчитаем эвристику
    if feats.get("rule_score") is None:
        feats["rule_score"] = _heuristic_rule_score(feats)

    # объединение со скоры AI
    score = _fusion.fuse(feats.get("rule_score"), feats.get("ai_score"), cfg)

    ok, reason = risk_manager.check(feats, cfg)
    price = float(feats["market"]["price"] or 0.0)
    atr_pct = float(feats["indicators"]["atr_pct"] or 0.0)

    BUY_TH = float(getattr(cfg, "SCORE_BUY_MIN", 0.6))
    SELL_TH = float(getattr(cfg, "SCORE_SELL_MIN", 0.4))
    SLx = float(getattr(cfg, "SL_ATR_MULT", 1.5))
    TPx = float(getattr(cfg, "TP_ATR_MULT", 2.5))

    decision: Dict[str, Any] = {
        "action": "hold",
        "size": "0",
        "sl": None,
        "tp": None,
        "trail": None,
        "score": score,
        "explain": {
            "ok": ok,
            "reason": reason,
            "rule_score": feats.get("rule_score"),
            "ai_score": feats.get("ai_score"),
            "ema_fast": feats["indicators"]["ema_fast"],
            "ema_slow": feats["indicators"]["ema_slow"],
            "rsi": feats["indicators"]["rsi"],
            "macd_hist": feats["indicators"]["macd_hist"],
            "atr_pct": atr_pct,
        },
    }

    if not ok:
        metrics.inc("decide_blocked_total", {"reason": reason})
        return decision

    # BUY
    if score >= BUY_TH and price > 0:
        size = _position_size_buy(cfg, price)
        sl = price * (1.0 - (SLx * atr_pct / 100.0)) if atr_pct > 0 else None
        tp = price * (1.0 + (TPx * atr_pct / 100.0)) if atr_pct > 0 else None
        decision.update(
            {
                "action": "buy",
                "size": str(size),
                "sl": sl,
                "tp": tp,
            }
        )
    # SELL
    elif score <= SELL_TH and price > 0:
        # По нашей карте операции с позициями делает use-case/positions.manager,
        # здесь отдаём рекомендацию: «sell» без указания размера — или фиксированный %
        frac = float(getattr(cfg, "SELL_SIGNAL_FRACTION", 0.5))
        decision.update(
            {
                "action": "sell",
                "size": str(frac),  # трактуется use-case как доля открытой позиции
                "sl": None,
                "tp": None,
            }
        )

    metrics.inc("bot_decision_total", {"action": decision["action"]})
    return decision
