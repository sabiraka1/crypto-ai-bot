# -*- coding: utf-8 -*-
"""
Robust feature aggregator with safe OHLCV fetch + graceful fallbacks.

Path: src/crypto_ai_bot/trading/signals/signal_aggregator.py
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fetch_ohlcv_with_retry(ex, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
    for i in range(3):
        try:
            if hasattr(ex, "load_markets"):
                ex.load_markets(reload=False)
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit) or []
            if ohlcv:
                return ohlcv
        except Exception:
            time.sleep(0.5 * (i + 1))
            try:
                if "/" not in symbol and "-" in symbol:
                    alt = symbol.replace("-", "/")
                    ohlcv = ex.fetch_ohlcv(alt, timeframe=timeframe, limit=limit) or []
                    if ohlcv:
                        return ohlcv
            except Exception:
                pass
    return []


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    diff = close.diff().fillna(0.0)
    gain = diff.clip(lower=0.0)
    loss = (-diff).clip(lower=0.0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0).clip(0, 100)


def _macd(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd = ema_fast - ema_slow
    signal_line = _ema(macd, signal)
    hist = macd - signal_line
    return hist


def _atr_abs(df: pd.DataFrame, period: int = 14) -> float:
    """ATR в абсолютных единицах цены (не %)."""
    hl = df["high"] - df["low"]
    pc = df["close"].shift(1)
    hc = (df["high"] - pc).abs()
    lc = (df["low"] - pc).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=1).mean().iloc[-1]
    return float(atr)


def _rule_score(ema20: float, ema50: float, atr_pct: float) -> float:
    # простая нормализация тренда: чем дальше 20 от 50, тем сильнее сигнал
    # 0.5 — нейтрально
    diff = ema20 - ema50
    scale = max(1e-6, atr_pct / 100.0)  # защита от деления на 0
    raw = math.tanh(diff / (scale * 10))
    score = 0.5 + 0.5 * raw
    return float(max(0.0, min(1.0, score)))


def aggregate_features(cfg, exchange, *, symbol: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Возвращает словарь с ключами:
      - indicators: {price, ema20, ema50, rsi, macd_hist, atr, atr_pct}
      - market: {condition}
      - rule_score: float [0..1]

    Никогда не бросает исключения — в случае отсутствия OHLCV вернёт минимум на основе тикера.
    """
    try:
        symbol = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")
        timeframe = getattr(cfg, "TIMEFRAME", "15m")
        period = int(getattr(cfg, "ATR_PERIOD", 14))
        limit = int(limit or getattr(cfg, "AGGREGATOR_LIMIT", getattr(cfg, "OHLCV_LIMIT", 200) or 200))

        ohlcv = _fetch_ohlcv_with_retry(exchange, symbol, timeframe, limit)
        if not ohlcv:
            # Fallback — используем last price из тикера и дефолтные индикаторы
            price = None
            try:
                t = exchange.fetch_ticker(symbol) or {}
                price = _safe_float(t.get("last") or t.get("close"))
            except Exception:
                price = None
            if price is None:
                price = 0.0

            indicators = {
                "price": float(price),
                "ema20": float(price),
                "ema50": float(price),
                "rsi": 50.0,
                "macd_hist": 0.0,
                "atr": 0.0,
                "atr_pct": 0.0,
            }
            return {
                "indicators": indicators,
                "market": {"condition": "unknown"},
                "rule_score": 0.5,
            }

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["ts"], unit="ms")

        ema20_series = _ema(df["close"], 20)
        ema50_series = _ema(df["close"], 50)

        rsi_series = _rsi(df["close"], 14)
        macd_hist_series = _macd(df["close"], 12, 26, 9)

        atr_abs = _atr_abs(df, period=period)
        price = float(df["close"].iloc[-1])
        atr_pct = (atr_abs / price * 100.0) if price else 0.0

        ema20 = float(ema20_series.iloc[-1])
        ema50 = float(ema50_series.iloc[-1])
        rsi_val = float(rsi_series.iloc[-1])
        macd_hist = float(macd_hist_series.iloc[-1])

        rule = _rule_score(ema20, ema50, atr_pct)
        condition = "bullish" if ema20 >= ema50 else "bearish"

        indicators = {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi_val,
            "macd_hist": macd_hist,
            "atr": float(atr_abs),
            "atr_pct": float(atr_pct),
        }
        return {
            "indicators": indicators,
            "market": {"condition": condition},
            "rule_score": rule,
        }
    except Exception:
        # максимально мягкий fallback
        return {
            "indicators": {"price": 0.0, "ema20": 0.0, "ema50": 0.0, "rsi": 50.0, "macd_hist": 0.0, "atr": 0.0, "atr_pct": 0.0},
            "market": {"condition": "unknown"},
            "rule_score": 0.5,
        }
