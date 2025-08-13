# src/crypto_ai_bot/trading/signals/signal_aggregator.py
from __future__ import annotations

import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

import pandas as pd
import numpy as np

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
    # True Range
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
    vr = float(vol.iloc[-1] / vol_sma20.iloc[-1]) if vol_sma20.iloc[-1] and not np.isnan(vol_sma20.iloc[-1]) else None
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
    # веса как обсуждали
    score += 0.20 * (1.0 if ind.get("rsi") is not None and 30 < ind["rsi"] < 70 else 0.0)  # «в рабочей зоне»
    score += 0.20 * (1.0 if ind.get("macd_hist", 0) > 0 else 0.0)
    score += 0.20 * (1.0 if ind.get("ema9", 0) > ind.get("ema21", 0) else 0.0)
    score += 0.15 * (1.0 if ind.get("ema20", 0) > ind.get("ema50", 0) else 0.0)
    vr = ind.get("volume_ratio")
    if vr is not None and np.isfinite(vr):
        score += 0.15 * _clamp(vr / 2.0, 0.0, 1.0)  # 2×среднего → +0.15
    # BB_reentry не считаем — можно добавить позже
    return _clamp(score)

# ----------------------- Public: aggregate_features -----------------------

def aggregate_features(cfg, exchange, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Возвращает:
        {
          "symbol", "timeframe", "timestamp",
          "indicators": {...}, "rule_score", "ai_score",
          "data_quality": {...},
          "context": {"market_condition": "..."}
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

    # 5) AI-score (фолбэк, бот потом сам «сфьюзит» rule+ai)
    ai_score = float(getattr(cfg, "AI_FAILOVER_SCORE", 0.55))

    # 6) Качество данных
    data_quality = {
        "primary_candles": int(len(dfs["15m"])),
        "timeframes_ok": tf_ok,
        "timeframes_failed": tf_failed,
        "indicators_count": 3,  # rsi, macd_hist, atr (+ema/vol не считаем в этот счётчик)
    }

    out = {
        "symbol": symbol,
        "timeframe": "15m",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "indicators": ind15,
        "rule_score": float(rule),
        "ai_score": float(ai_score),
        "data_quality": data_quality,
        "context": {"market_condition": mkt_cond},
    }

    logger.info(f"✅ Features aggregated: rule={rule:.3f}, ai={ai_score:.3f}, ind={data_quality['indicators_count']}")
    return out
