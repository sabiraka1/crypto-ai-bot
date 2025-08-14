
# -*- coding: utf-8 -*-
from __future__ import annotations

# crypto_ai_bot/analysis/technical_indicators.py
# ----------------------------------------------
# Единый источник истины для индикаторов:
# - calculate_all_indicators(df): возвращает DataFrame c RSI, MACD histogram, ATR, EMA(9/21/20/50), volume_ratio
# - get_unified_atr(df, period=14, method='ema'|'sma'): расчёт ATR
# - IndicatorCalculator: быстрые EMA/RSI/MACD-блоки (используются в aggregator)
# Ожидается, что входной df имеет колонки: open, high, low, close, volume и индекс времени (UTC).

import os
from typing import Dict, Iterable, Optional
import numpy as np
import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(span=period, adjust=False, min_periods=period).mean()
    ma_down = down.ewm(span=period, adjust=False, min_periods=period).mean()
    rs = ma_up / (ma_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd = ema_fast - ema_slow
    signal_line = _ema(macd, signal)
    hist = macd - signal_line
    return hist


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr


def get_unified_atr(df: pd.DataFrame, period: int = 14, method: str = None) -> pd.Series:
    # Возвращает ряд ATR. method задаётся ENV RISK_ATR_METHOD (ema|sma), по умолчанию EMA.
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    m = (method or os.getenv("RISK_ATR_METHOD") or "ema").lower()
    tr = _true_range(df)
    if m == "sma":
        atr = _sma(tr, period)
    else:
        atr = tr.ewm(span=period, adjust=False, min_periods=period).mean()
    return atr


def calculate_all_indicators(df: pd.DataFrame, use_cache: bool = True) -> pd.DataFrame:
    # Строит единый набор индикаторов и возвращает копию исходного df с новыми колонками.
    if df is None or df.empty:
        return pd.DataFrame(columns=["open","high","low","close","volume","rsi","macd_hist","ema9","ema21","ema20","ema50","atr","volume_ratio"])

    out = df.copy()

    # Базовые индикаторы
    out["rsi"] = _rsi(out["close"], 14)
    out["macd_hist"] = _macd_hist(out["close"])
    out["ema9"]  = _ema(out["close"], 9)
    out["ema21"] = _ema(out["close"], 21)
    out["ema20"] = _ema(out["close"], 20)
    out["ema50"] = _ema(out["close"], 50)

    # ATR
    out["atr"] = get_unified_atr(out, period=14)

    # Объёмная активность: отношение текущего объёма к SMA(20) объёма
    vol_mean = _sma(out["volume"].astype("float64"), 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["volume_ratio"] = (out["volume"] / vol_mean).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return out


class IndicatorCalculator:
    # Вспомогательный класс для быстрых EMA/RSI/MACD расчётов (серии на вход/выход).
    def calculate_emas(self, series: pd.Series, periods: Iterable[int]) -> Dict[int, pd.Series]:
        out: Dict[int, pd.Series] = {}
        s = series.astype("float64")
        for p in periods:
            out[int(p)] = _ema(s, int(p))
        return out

    def rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        return _rsi(series.astype("float64"), period)

    def macd_hist(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
        return _macd_hist(series.astype("float64"), fast=fast, slow=slow, signal=signal)
