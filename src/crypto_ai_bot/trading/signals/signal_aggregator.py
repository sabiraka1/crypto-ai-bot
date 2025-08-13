# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

import pandas as pd
import numpy as np

from crypto_ai_bot.context.snapshot import build_context_snapshot

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

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill().fillna(50.0)

def _macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return (macd_line - signal_line)

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))

# ----------------------- Indicators & Scoring -----------------------

def _compute_indicators_15m(df15: pd.DataFrame) -> Dict[str, Any]:
    """Основные индикаторы и derived-метрики на 15m."""
    if df15.empty:
        raise ValueError("empty df15")

    close = df15["close"]
    vol = df15["volume"]

    out: Dict[str, Any] = {}
    out["ema9"] = float(_ema(close, 9).iloc[-1])
    out["ema21"] = float(_ema(close, 21).iloc[-1])
    out["ema20"] = float(_ema(close, 20).iloc[-1])
    out["ema50"] = float(_ema(close, 50).iloc[-1])

    rsi = _rsi(close, 14)
    out["rsi"] = float(rsi.iloc[-1])

    macd_h = _macd_hist(close, 12, 26, 9)
    out["macd_hist"] = float(macd_h.iloc[-1])

    atr = _atr(df15, 14)
    out["atr"] = float(atr.iloc[-1])

    out["price"] = float(close.iloc[-1])
    out["atr_pct"] = float(out["atr"] / out["price"] * 100.0) if out["price"] > 0 else None

    vol_sma20 = vol.rolling(20).mean()
    vr_val = vol_sma20.iloc[-1] if len(vol_sma20) else np.nan
    vr = float(vol.iloc[-1] / vr_val) if (vr_val and not np.isnan(vr_val)) else None
    out["volume_ratio"] = vr

    return out

def _compute_trend_4h(df4h: pd.DataFrame) -> Optional[bool]:
    """bull=True, bear=False, None=неопределённо"""
    if df4h.empty:
        return None
    ema20_4h = _ema(df4h["close"], 20).iloc[-1]
    ema50_4h = _ema(df4h["close"], 50).iloc[-1]
    if np.isnan(ema20_4h) or np.isnan(ema50_4h):
        return None
    return bool(ema20_4h > ema50_4h)

def _market_condition(ind_15m: Dict[str, Any], trend_4h: Optional[bool]) -> str:
    if trend_4h is True:
        return "bull_4h"
    if trend_4h is False:
        return "bear_4h"
    if ind_15m.get("ema20", 0) > ind_15m.get("ema50", 0):
        return "bull_15m"
    if ind_15m.get("ema20", 0) < ind_15m.get("ema50", 0):
        return "bear_15m"
    return "SIDEWAYS"

def _rule_score(ind: Dict[str, Any]) -> float:
    """Весовая модель без AI: 0..1"""
    score = 0.0
    score += 0.20 * (1.0 if ind.get("rsi") is not None and 30 < ind["rsi"] < 70 else 0.0)
    score += 0.20 * (1.0 if ind.get("macd_hist", 0) > 0 else 0.0)
    score += 0.20 * (1.0 if ind.get("ema9", 0) > ind.get("ema21", 0) else 0.0)
    score += 0.15 * (1.0 if ind.get("ema20", 0) > ind.get("ema50", 0) else 0.0)
    vr = ind.get("volume_ratio")
    if vr is not None and np.isfinite(vr):
        score += 0.15 * _clamp(vr / 2.0, 0.0, 1.0)  # 2×среднего → +0.15
    return _clamp(score)

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
    """Применяет мягкие штрафы/бонусы по ENV. Возвращает (скор_после, детали)."""
    if not int(os.getenv("USE_CONTEXT_PENALTIES", "0")):
        return base_score, {"enabled": False, "applied": []}

    clamp_min = float(os.getenv("CTX_SCORE_CLAMP_MIN", "0.0"))
    clamp_max = float(os.getenv("CTX_SCORE_CLAMP_MAX", "1.0"))

    # BTC Dominance (штраф только для альтов — если включено)
    penalties = []
    score = base_score

    try:
        alts_only = int(os.getenv("CTX_BTC_DOM_ALTS_ONLY", "1")) == 1
        dom_thresh = float(os.getenv("CTX_BTC_DOM_THRESH", "52.0"))
        dom_pen = float(os.getenv("CTX_BTC_DOM_PENALTY", "-0.05"))

        if snap.btc_dominance is not None:
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
        if snap.dxy_change_1d is not None and float(snap.dxy_change_1d) >= dxy_thr:
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
        if snap.fear_greed is not None:
            fng = float(snap.fear_greed)
            if fng >= fng_over:
                score += fng_pen
                penalties.append({"factor": "fear_greed_overheated", "value": fng, "delta": fng_pen})
            elif fng <= fng_under:
                score += fng_bonus
                penalties.append({"factor": "fear_greed_undershoot", "value": fng, "delta": fng_bonus})
    except Exception as e:
        logger.debug(f"ctx penalty fng skipped: {e}")

    score = _clamp(score, clamp_min, clamp_max)
    return score, {"enabled": True, "applied": penalties, "clamp": [clamp_min, clamp_max]}

# ----------------------- Public: aggregate_features -----------------------

def aggregate_features(cfg, exchange, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Возвращает:
        {
          "symbol", "timeframe", "timestamp",
          "indicators": {...}, "rule_score", "rule_score_penalized", "ai_score",
          "data_quality": {...},
          "context": {"market_condition": "...", "snapshot": {...}, "penalties": {...}}
        }
    """
    symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
    tfs = ["15m", "1h", "4h"]
    limit = int(getattr(cfg, "AGGREGATOR_LIMIT", 200))

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

    # 2) Индикаторы 15m и тренд 4h
    try:
        ind15 = _compute_indicators_15m(dfs["15m"])
    except Exception as e:
        logger.error(f"❌ Indicators computation failed: {e}")
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

    # 5) Подтягиваем «реальный» контекст
    try:
        snap = build_context_snapshot(cfg, exchange, symbol, timeframe="15m")
    except Exception as e:
        logger.warning(f"⚠️ Context snapshot failed: {e}")
        snap = None

    # 6) Применяем мягкие штрафы/бонусы контекста
    penalties_info: Dict[str, Any] = {"enabled": False, "applied": []}
    rule_penalized = rule
    if snap is not None:
        rule_penalized, penalties_info = _apply_context_penalties(symbol, rule, snap)

    # 7) AI-score (фолбэк — бот потом сам «сфьюзит» rule+ai)
    ai_score = float(getattr(cfg, "AI_FAILOVER_SCORE", 0.55))

    # 8) Качество данных
    data_quality = {
        "primary_candles": int(len(dfs["15m"])),
        "timeframes_ok": tf_ok,
        "timeframes_failed": tf_failed,
        "indicators_count": 5,  # rsi, macd_hist, ema-кроссы, atr, volume_ratio
    }

    # 9) Ответ
    ctx_payload: Dict[str, Any] = {"market_condition": mkt_cond}
    if snap is not None:
        ctx_payload["snapshot"] = {
            "btc_dominance": getattr(snap, "btc_dominance", None),
            "dxy_change_1d": getattr(snap, "dxy_change_1d", None),
            "fear_greed": getattr(snap, "fear_greed", None),
        }
        ctx_payload["penalties"] = penalties_info

    out = {
        "symbol": symbol,
        "timeframe": "15m",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "indicators": ind15,
        "rule_score": float(rule),
        "rule_score_penalized": float(rule_penalized),
        "ai_score": float(ai_score),
        "data_quality": data_quality,
        "context": ctx_payload,
    }

    logger.info(
        f"✅ Features aggregated: rule={rule:.3f} -> penalized={rule_penalized:.3f}, ai={ai_score:.3f}, "
        f"ind={data_quality['indicators_count']}"
    )
    return out
