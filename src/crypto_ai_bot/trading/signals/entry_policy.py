# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/trading/signals/entry_policy.py
------------------------------------------------
Компактные правила входа/выхода без дублирования индикаторов.
Опираться должны на агрегатор features из signals.signal_aggregator
и единую реализацию индикаторов из analysis.technical_indicators.

Подключение:
    from crypto_ai_bot.trading.signals.entry_policy import decide_entry, compute_sl_tp_by_atr, update_trailing_stop

Совместимость:
- Не тянет внешние зависимости, кроме numpy.
- Работает с любой структурой cfg (атрибуты/ENV), как в TradingBot.Settings.
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np


def _get(cfg, name: str, default):
    return float(getattr(cfg, name, default)) if isinstance(default, (int, float)) else getattr(cfg, name, default)


def decide_entry(indicators: Dict[str, Any], scores: Dict[str, float], cfg) -> Dict[str, Any]:
    """
    Решение об открытии позиции на основе индикаторов + скорингов.
    Возвращает словарь:
      {"action": "buy"|"sell"|None, "reason": str, "rule": float, "ai": float}
    """
    rule = float(scores.get("rule", 0.5))
    ai = float(scores.get("ai", _get(cfg, "AI_FAILOVER_SCORE", 0.55)))

    enforce_ai = int(getattr(cfg, "ENFORCE_AI_GATE", 1)) == 1
    ai_min = _get(cfg, "AI_MIN_TO_TRADE", 0.55)
    min_buy = _get(cfg, "MIN_SCORE_TO_BUY", 0.65)

    if enforce_ai and ai < ai_min:
        return {"action": None, "reason": f"ai<{ai_min}", "rule": rule, "ai": ai}

    if rule < min_buy:
        return {"action": None, "reason": f"rule<{min_buy}", "rule": rule, "ai": ai}

    rsi = indicators.get("rsi")
    ema20 = indicators.get("ema20") or 0.0
    ema50 = indicators.get("ema50") or 0.0

    # Лонг: тренд вверх и RSI не критический
    rsi_crit = _get(cfg, "RSI_CRITICAL", 90.0)
    if rsi is not None and rsi >= rsi_crit:
        # перекупленность — не открываем лонг
        pass
    else:
        if ema20 > ema50:
            return {"action": "buy", "reason": "ema20>ema50 + scores", "rule": rule, "ai": ai}

    # Шорт: тренд вниз и RSI не перепродан до абсурда
    if rsi is not None and rsi <= (100.0 - rsi_crit):
        pass
    else:
        if ema20 < ema50:
            return {"action": "sell", "reason": "ema20<ema50 + scores", "rule": rule, "ai": ai}

    return {"action": None, "reason": "neutral", "rule": rule, "ai": ai}


def compute_sl_tp_by_atr(entry: float, atr: float, side: str, cfg) -> Tuple[float, float]:
    """
    Возвращает (sl, tp) на основе ATR, с фолбэком на фикс-проценты из cfg.
    """
    if atr and np.isfinite(atr) and entry > 0:
        k1, k2 = 1.5, 2.5
        if side == "buy":
            sl = entry - k1 * atr
            tp = entry + k2 * atr
        else:
            sl = entry + k1 * atr
            tp = entry - k2 * atr
        return float(sl), float(tp)

    # Фолбэк на проценты
    stop_loss_pct = _get(cfg, "STOP_LOSS_PCT", 2.0)
    take_profit_pct = _get(cfg, "TAKE_PROFIT_PCT", 1.5)

    if side == "buy":
        sl = entry * (1 - stop_loss_pct / 100.0)
        tp = entry * (1 + take_profit_pct / 100.0)
    else:
        sl = entry * (1 + stop_loss_pct / 100.0)
        tp = entry * (1 - take_profit_pct / 100.0)

    return float(sl), float(tp)


def update_trailing_stop(current_price: float, side: str, trailing_max: Optional[float], enable: bool = True) -> Optional[float]:
    """
    Обновляет трейлинг-значение (для лонга — максимум цены).
    Для шорта можно расширить под минимум, но оставим компактно.
    """
    if not enable:
        return trailing_max
    if side == "buy":
        return max(trailing_max or current_price, current_price)
    # для sell-режима можно сделать trailing_min — опущено ради компактности
    return trailing_max
