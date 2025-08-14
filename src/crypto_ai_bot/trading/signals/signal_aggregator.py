# -*- coding: utf-8 -*-
from __future__ import annotations

"""
signals/signal_aggregator.py
---------------------------------
Упрощённый и унифицированный агрегатор фич без локальных дубликатов индикаторов.

Что изменилось по сравнению с текущей версией:
- ❌ Убраны локальные реализации EMA/RSI/MACD/ATR.
- ✅ Все индикаторы/ATR берём из crypto_ai_bot.analysis.technical_indicators
  (единый кэш, единая формула ATR, согласованность со всем проектом).
- ♻️ Лёгкая обратная совместимость по структуре ответа aggregate_features().
- ➕ Дополнительно возвращаем frames['15m'] с DataFrame 15m (не ломает совместимость),
  чтобы RiskManager мог строить динамический SL без фолбэка.

Файл совместим с TradingBot/entry_policy.
"""

import os
import logging
from typing import Dict, Any, List, Tuple, Optional, Sequence
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_ai_bot.context.snapshot import build_context_snapshot

# Индикаторы/ATR из единого модуля
from crypto_ai_bot.analysis.technical_indicators import (
    calculate_all_indicators,   # возвращает DataFrame c индикаторами (rsi, macd_hist, ema_*, atr, volume_ratio, ...)
    get_unified_atr,            # единая функция ATR (для точечных расчётов при необходимости)
    IndicatorCalculator,        # быстрые EMA/RSI/MACD-блоки (без дубликатов логики)
)

logger = logging.getLogger(__name__)


# ----------------------- Helpers -----------------------

def _ohlcv_to_df(ohlcv: List[list]) -> pd.DataFrame:
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


# ----------------------- Indicators & Scoring -----------------------

def _compute_indicators_15m(df15: pd.DataFrame) -> Dict[str, Any]:
    """Основные индикаторы и derived-метрики на 15m (через analysis.*)."""
    if df15 is None or df15.empty:
        raise ValueError("empty df15")

    # 1) Считаем «единый» пакет индикаторов (кэш/ATR уже внутри)
    ind_df = calculate_all_indicators(df15, use_cache=True)

    # Последние значения (с защитой от NaN)
    def _last(col: str) -> Optional[float]:
        try:
            v = float(ind_df[col].iloc[-1])
            return v if np.isfinite(v) else None
        except Exception:
            return None

    # 2) EMA 9/21/20/50 — быстрым калькулятором (в нём используются те же алгоритмы)
    calc = IndicatorCalculator()
    emas = calc.calculate_emas(ind_df["close"], [9, 21, 20, 50])
    ema9 = float(emas[9].iloc[-1]) if len(emas[9]) else np.nan
    ema21 = float(emas[21].iloc[-1]) if len(emas[21]) else np.nan
    ema20 = float(emas[20].iloc[-1]) if len(emas[20]) else np.nan
    ema50 = float(emas[50].iloc[-1]) if len(emas[50]) else np.nan

    out: Dict[str, Any] = {
        # Унифицированные индикаторы
        "rsi": _last("rsi"),
        "macd_hist": _last("macd_hist"),
        "atr": _last("atr"),
        "price": _last("close"),
        "volume_ratio": _last("volume_ratio"),
        # EMA (для совместимости со старым кодом/логикой правил)
        "ema9": float(ema9) if np.isfinite(ema9) else None,
        "ema21": float(ema21) if np.isfinite(ema21) else None,
        "ema20": float(ema20) if np.isfinite(ema20) else None,
        "ema50": float(ema50) if np.isfinite(ema50) else None,
    }

    # Derived: ATR%
    if out.get("atr") and out.get("price"):
        out["atr_pct"] = float(out["atr"] / out["price"] * 100.0) if out["price"] > 0 else None
    else:
        out["atr_pct"] = None

    return out


def _compute_trend_4h(df4h: pd.DataFrame) -> Optional[bool]:
    """bull=True, bear=False, None=неопределённо (через те же EMA-алгоритмы)."""
    if df4h is None or df4h.empty:
        return None
    try:
        calc = IndicatorCalculator()
        emas = calc.calculate_emas(pd.to_numeric(df4h["close"], errors="coerce").astype("float64"), [20, 50])
        ema20_4h = float(emas[20].iloc[-1]) if len(emas[20]) else np.nan
        ema50_4h = float(emas[50].iloc[-1]) if len(emas[50]) else np.nan
        if not (np.isfinite(ema20_4h) and np.isfinite(ema50_4h)):
            return None
        return bool(ema20_4h > ema50_4h)
    except Exception:
        return None


def _market_condition(ind_15m: Dict[str, Any], trend_4h: Optional[bool]) -> str:
    if trend_4h is True:
        return "bull_4h"
    if trend_4h is False:
        return "bear_4h"
    if (ind_15m.get("ema20") or 0) > (ind_15m.get("ema50") or 0):
        return "bull_15m"
    if (ind_15m.get("ema20") or 0) < (ind_15m.get("ema50") or 0):
        return "bear_15m"
    return "SIDEWAYS"


def _rule_score(ind: Dict[str, Any]) -> float:
    """Простая весовая модель без AI: 0..1 (оставлена как была)."""
    score = 0.0
    score += 0.20 * (1.0 if ind.get("rsi") is not None and 30 < ind["rsi"] < 70 else 0.0)
    score += 0.20 * (1.0 if (ind.get("macd_hist") or 0) > 0 else 0.0)
    score += 0.20 * (1.0 if (ind.get("ema9") or 0) > (ind.get("ema21") or 0) else 0.0)
    score += 0.15 * (1.0 if (ind.get("ema20") or 0) > (ind.get("ema50") or 0) else 0.0)
    vr = ind.get("volume_ratio")
    if vr is not None and np.isfinite(vr):
        score += 0.15 * _clamp(vr / 2.0, 0.0, 1.0)  # 2× среднего объёма → +0.15
    return max(0.0, min(1.0, score))


# ----------------------- Context penalties -----------------------

def _is_alt_symbol(symbol: str) -> bool:
    """Грубая эвристика: альт — если не BTC/xxx и не xxx/BTC."""
    s = (symbol or "").upper()
    return not (s.startswith("BTC/") or s.endswith("/BTC"))


def _apply_context_penalties(
    symbol: str,
    base_score: float,
    snap: Any,  # ContextSnapshot
) -> Tuple[float, Dict[str, Any]]:
    """
    Применяет мягкие штрафы/бонусы по ENV.
    Возвращает (скор_после, детали).
    """
    if not int(os.getenv("USE_CONTEXT_PENALTIES", "0")):
        return base_score, {"enabled": False, "applied": []}

    clamp_min = float(os.getenv("CTX_SCORE_CLAMP_MIN", "0.0"))
    clamp_max = float(os.getenv("CTX_SCORE_CLAMP_MAX", "1.0"))

    penalties = []
    score = base_score

    # BTC Dominance (штраф только для альтов — если включено)
    try:
        alts_only = int(os.getenv("CTX_BTC_DOM_ALTS_ONLY", "1")) == 1
        dom_thresh = float(os.getenv("CTX_BTC_DOM_THRESH", "52.0"))
        dom_pen = float(os.getenv("CTX_BTC_DOM_PENALTY", "-0.05"))

        if getattr(snap, "btc_dominance", None) is not None:
            cond_alts = (not alts_only) or _is_alt_symbol(symbol)
            if cond_alts and float(snap.btc_dominance) >= dom_thresh:
                score += dom_pen
                penalties.append({"factor": "btc_dominance", "value": snap.btc_dominance, "delta": dom_pen})
    except Exception as e:
        logger.debug(f"ctx penalty btc_dominance skipped: {e}")

    # DXY дневное изменение
    try:
        dxy_thr = float(os.getenv("CTX_DXY_DELTA_THRESH", "0.5"))
        dxy_pen = float(os.getenv("CTX_DXY_PENALTY", "-0.05"))
        if getattr(snap, "dxy_change_1d", None) is not None and float(snap.dxy_change_1d) >= dxy_thr:
            score += dxy_pen
            penalties.append({"factor": "dxy_change_1d", "value": snap.dxy_change_1d, "delta": dxy_pen})
    except Exception as e:
        logger.debug(f"ctx penalty dxy skipped: {e}")

    # Fear & Greed
    try:
        fng_over = float(os.getenv("CTX_FNG_OVERHEATED", "75"))
        fng_under = float(os.getenv("CTX_FNG_UNDERSHOOT", "25"))
        fng_pen = float(os.getenv("CTX_FNG_PENALTY", "-0.05"))
        fng_bonus = float(os.getenv("CTX_FNG_BONUS", "0.03"))
        if getattr(snap, "fear_greed", None) is not None:
            fng = float(snap.fear_greed)
            if fng >= fng_over:
                score += fng_pen
                penalties.append({"factor": "fear_greed_overheated", "value": fng, "delta": fng_pen})
            elif fng <= fng_under:
                score += fng_bonus
                penalties.append({"factor": "fear_greed_undershoot", "value": fng, "delta": fng_bonus})
    except Exception as e:
        logger.debug(f"ctx penalty fng skipped: {e}")

    score = max(clamp_min, min(clamp_max, score))
    return score, {"enabled": True, "applied": penalties, "clamp": [clamp_min, clamp_max]}


# ----------------------- Public API (back-compat signature) -----------------------

def aggregate_features(
    cfg,
    exchange,
    # старые параметры — оставлены для совместимости со старыми вызовами:
    symbol: str = "BTC/USDT",
    timeframe: Optional[str] = None,   # игнорируем, у нас мульти-TF
    timeframes: Optional[Sequence[str]] = None,
    limit: int = 200,
    settings: Any = None,
    use_context_penalties: Optional[bool] = None,
    snapshot: Any = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Возвращает единый пакет фич (совместим с прежней структурой).
    """
    # приоритет: явные аргументы -> cfg -> дефолт
    symbol = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")

    # поддержка старого аргумента timeframe/timeframes
    if timeframes is None:
        timeframes = getattr(cfg, "AGGREGATOR_TIMEFRAMES", None)
    tfs = list(timeframes) if timeframes else ["15m", "1h", "4h"]

    if not limit:
        limit = int(getattr(cfg, "AGGREGATOR_LIMIT", 200))

    # Перекрыть флаг USE_CONTEXT_PENALTIES можно аргументом функции
    if use_context_penalties is not None:
        os.environ["USE_CONTEXT_PENALTIES"] = "1" if use_context_penalties else "0"

    logger.info(f"🎯 Aggregating features for {symbol} ({tfs}, limit={limit})")

    # 1) Скачиваем свечи
    dfs: Dict[str, pd.DataFrame] = {}
    tf_ok: List[str] = []
    tf_failed: List[str] = []

    for tf in tfs:
        try:
            raw = exchange.get_ohlcv(symbol, timeframe=tf, limit=limit)
            df = _ohlcv_to_df(raw)
            if df.empty:
                raise RuntimeError("empty dataframe")
            dfs[tf] = df
            tf_ok.append(tf)
        except Exception as e:
            logger.error(f"❌ Fetch {tf} failed: {e}")
            tf_failed.append(tf)

    if "15m" not in dfs:
        return {"error": "no_primary_data"}

    # 2) Индикаторы 15m и тренд 4h (через unified analysis.*)
    try:
        ind15 = _compute_indicators_15m(dfs["15m"])
    except Exception as e:
        logger.error(f"❌ Indicators computation failed: {e}", exc_info=True)
        return {"error": "indicators_failed"}

    trend4h = _compute_trend_4h(dfs.get("4h", pd.DataFrame()))
    ind15["trend_4h_bull"] = trend4h

    # 3) Рыночное состояние
    mkt_cond = _market_condition(ind15, trend4h)

    # 4) Rule-score (без AI)
    try:
        rule = _rule_score(ind15)
    except Exception as e:
        logger.warning(f"⚠️ Rule score failed: {e}")
        rule = 0.5

    # 5) Реальный контекст (если снапшот не прокинут аргументом — соберём сами)
    if snapshot is None:
        try:
            snapshot = build_context_snapshot(cfg, exchange, symbol, timeframe="15m")
        except Exception as e:
            logger.warning(f"⚠️ Context snapshot failed: {e}")
            snapshot = None

    # 6) Мягкие штрафы/бонусы контекста
    penalties_info: Dict[str, Any] = {"enabled": False, "applied": []}
    rule_penalized = rule
    if snapshot is not None:
        rule_penalized, penalties_info = _apply_context_penalties(symbol, rule, snapshot)

    # 7) AI-score (fallback, если модель ещё не готова)
    ai_score = float(getattr(cfg, "AI_FAILOVER_SCORE", 0.55))

    # 8) Качество данных
    data_quality = {
        "primary_candles": int(len(dfs["15m"])),
        "timeframes_ok": tf_ok,
        "timeframes_failed": tf_failed,
        "indicators_count": 5,  # rsi, macd_hist, ema-кроссы, atr, volume_ratio
    }

    # 9) Пакуем ответ + совместимые поля для /status
    ctx_payload: Dict[str, Any] = {"market_condition": mkt_cond}
    if snapshot is not None:
        ctx_payload["snapshot"] = {
            "btc_dominance": getattr(snapshot, "btc_dominance", None),
            "dxy_change_1d": getattr(snapshot, "dxy_change_1d", None),
            "fear_greed": getattr(snapshot, "fear_greed", None),
        }
        ctx_payload["penalties"] = penalties_info

    out: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": "15m",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),

        "indicators": ind15,
        "rule_score": float(rule),
        "rule_score_penalized": float(rule_penalized),
        "ai_score": float(ai_score),
        "data_quality": data_quality,
        "context": ctx_payload,

        # ✔️ Добавочно — отдадим фрейм 15m для RiskManager (динамический SL)
        "frames": {"15m": dfs["15m"]},

        # Совместимые поля, чтобы старый /status ничего не ломал:
        "scores": {
            "rule": float(rule),
            "ai": float(ai_score),
            "total_hint": float(rule_penalized),
        },
        "market": {
            "condition": mkt_cond,
            "atr_pct": ind15.get("atr_pct"),
        },
        "data": data_quality,
    }

    logger.info(
        f"✅ Features aggregated: rule={rule:.3f} -> penalized={rule_penalized:.3f}, "
        f"ai={ai_score:.3f}, ind={data_quality['indicators_count']}"
    )
    return out
