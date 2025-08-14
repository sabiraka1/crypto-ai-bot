# -*- coding: utf-8 -*-
"""
Signals aggregator.
Path: src/crypto_ai_bot/signals/signal_aggregator.py

Goal: compute indicators (EMA/RSI/MACD/ATR) in a single place (no duplicates)
and return a uniform payload for the trading engine.

aggregate_features(cfg, exchange, symbol: str, limit: int=200) -> dict
Returns:
{
  "indicators": {
     "price": float,
     "ema20": float, "ema50": float,
     "rsi": float,
     "macd_hist": float,
     "atr": float, "atr_pct": float,
     "volume_ratio": float,
  },
  "market": {"condition": "bullish|bearish|neutral"},
  "rule_score": float,
  "rule_score_penalized": float,
}
"""
from __future__ import annotations

from typing import Any, Dict, List
import math

try:
    from crypto_ai_bot.analysis.indicators import ema, rsi, macd, get_unified_atr
except Exception:
    # fallback if path differs
    from crypto_ai_bot.analysis import indicators as _ind  # type: ignore
    ema = _ind.ema; rsi = _ind.rsi; macd = _ind.macd; get_unified_atr = _ind.get_unified_atr  # type: ignore


def _safe(val, default=0.0) -> float:
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _fetch_ohlcv(exchange: Any, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
    if not hasattr(exchange, "fetch_ohlcv"):
        return []
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit) or []
        return data
    except Exception:
        return []


def _last(arr: List[float]) -> float:
    return float(arr[-1]) if arr else 0.0


def _avg(arr: List[float]) -> float:
    return float(sum(arr) / len(arr)) if arr else 0.0


def _market_condition(price: float, ema20: float, ema50: float, macd_hist: float, rsi_v: float) -> str:
    bullish = (ema20 > ema50 and macd_hist > 0 and 45 <= rsi_v <= 70)
    bearish = (ema20 < ema50 and macd_hist < 0 and 30 <= rsi_v <= 55)
    if bullish:
        return "bullish"
    if bearish:
        return "bearish"
    return "neutral"


def _rule_score(ema20: float, ema50: float, macd_hist: float, rsi_v: float) -> float:
    score = 0.5
    score += 0.2 if ema20 > ema50 else -0.2
    score += 0.2 if macd_hist > 0 else -0.2
    if 45 <= rsi_v <= 60:
        score += 0.1
    elif rsi_v > 70 or rsi_v < 30:
        score -= 0.1
    return max(0.0, min(1.0, score))


def aggregate_features(cfg, exchange: Any, symbol: str, limit: int = 200) -> Dict[str, Any]:
    tf = getattr(cfg, "TIMEFRAME", "15m")
    candles = _fetch_ohlcv(exchange, symbol, tf, limit)
    if not candles or len(candles) < 20:
        return {"error": "no ohlcv"}

    # unpack
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows  = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    # indicators
    ema20_series = ema(closes, 20)
    ema50_series = ema(closes, 50)
    rsi_series = rsi(closes, int(getattr(cfg, "RSI_PERIOD", 14)))
    macd_line, macd_signal, macd_hist = macd(closes, 12, 26, 9)

    atr_period = int(getattr(cfg, "ATR_PERIOD", 14))
    atr_method = str(getattr(cfg, "RISK_ATR_METHOD", "ewm"))
    atr_series = get_unified_atr(atr_method, highs, lows, closes, period=atr_period)

    price = _last(closes)
    ema20_v = _last(ema20_series)
    ema50_v = _last(ema50_series)
    rsi_v   = _last(rsi_series)
    macd_hist_v = _last(macd_hist)
    atr_v   = _last(atr_series)

    atr_pct = (atr_v / price * 100.0) if (price > 0 and atr_v > 0) else 0.0
    vol_mean20 = _avg(volumes[-20:])
    volume_ratio = (volumes[-1] / vol_mean20) if vol_mean20 > 0 else 1.0

    cond = _market_condition(price, ema20_v, ema50_v, macd_hist_v, rsi_v)
    rs = _rule_score(ema20_v, ema50_v, macd_hist_v, rsi_v)

    # penalty placeholder (context penalties can be added here later)
    rs_pen = rs
    if int(getattr(cfg, "USE_CONTEXT_PENALTIES", 0)) == 1:
        # without external sources we keep it equal (hook point for future)
        rs_pen = max(0.0, min(1.0, rs))

    ind = {
        "price": _safe(price),
        "ema20": _safe(ema20_v),
        "ema50": _safe(ema50_v),
        "rsi": _safe(rsi_v),
        "macd_hist": _safe(macd_hist_v),
        "atr": _safe(atr_v),
        "atr_pct": _safe(atr_pct),
        "volume_ratio": _safe(volume_ratio, 1.0),
    }

    return {
        "indicators": ind,
        "market": {"condition": cond},
        "rule_score": float(rs),
        "rule_score_penalized": float(rs_pen),
    }
