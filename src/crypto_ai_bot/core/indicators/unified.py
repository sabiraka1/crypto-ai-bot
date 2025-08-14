
# -*- coding: utf-8 -*-
"""
crypto_ai_bot.core.indicators.unified
------------------------------------
Р•РґРёРЅС‹Р№ РЅР°Р±РѕСЂ РёРЅРґРёРєР°С‚РѕСЂРѕРІ (Phase 3).
Р’СЃРµ СЂР°СЃС‡С‘С‚С‹ РІ РѕРґРЅРѕРј РјРµСЃС‚Рµ, Р±РµР· Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ СЂР°Р·Р±СЂРѕСЃР°РЅРЅС‹С… СЂРµР°Р»РёР·Р°С†РёР№.
Р’РѕР·РІСЂР°С‰Р°РµРј pandas.Series РґР»СЏ РІРµРєС‚РѕСЂРЅС‹С… С„СѓРЅРєС†РёР№ Рё float РґР»СЏ *_last.
"""
from __future__ import annotations

from typing import Iterable, Tuple
import numpy as np
import pandas as pd


def _to_series(x: Iterable[float] | pd.Series) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.astype(float)
    return pd.Series(list(x), dtype=float)


# --- Moving Averages ---
def sma(series: Iterable[float] | pd.Series, window: int) -> pd.Series:
    s = _to_series(series)
    return s.rolling(window=window, min_periods=1).mean()


def ema(series: Iterable[float] | pd.Series, span: int) -> pd.Series:
    s = _to_series(series)
    return s.ewm(span=span, adjust=False).mean()


# --- RSI ---
def rsi(series: Iterable[float] | pd.Series, period: int = 14) -> pd.Series:
    s = _to_series(series)
    delta = s.diff().fillna(0.0)
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi_v = 100.0 - (100.0 / (1.0 + rs))
    return rsi_v.fillna(50.0).clip(0.0, 100.0)


# --- MACD ---
def macd(series: Iterable[float] | pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    s = _to_series(series)
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# --- ATR ---
def true_range(high: Iterable[float] | pd.Series, low: Iterable[float] | pd.Series, close: Iterable[float] | pd.Series) -> pd.Series:
    h = _to_series(high)
    l = _to_series(low)
    c = _to_series(close)
    prev_close = c.shift(1)
    hl = (h - l).abs()
    hc = (h - prev_close).abs()
    lc = (l - prev_close).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr


def atr(high: Iterable[float] | pd.Series, low: Iterable[float] | pd.Series, close: Iterable[float] | pd.Series, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def atr_pct(high: Iterable[float] | pd.Series, low: Iterable[float] | pd.Series, close: Iterable[float] | pd.Series, period: int = 14) -> pd.Series:
    a = atr(high, low, close, period)
    c = _to_series(close).replace(0.0, np.nan)
    pct = (a / c) * 100.0
    return pct.fillna(0.0)


# --- Helpers (last values) ---
def ema_last(series: Iterable[float] | pd.Series, span: int) -> float:
    return float(ema(series, span).iloc[-1])


def rsi_last(series: Iterable[float] | pd.Series, period: int = 14) -> float:
    return float(rsi(series, period).iloc[-1])


def macd_hist_last(series: Iterable[float] | pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    _, _, h = macd(series, fast, slow, signal)
    return float(h.iloc[-1])


def atr_last(high: Iterable[float] | pd.Series, low: Iterable[float] | pd.Series, close: Iterable[float] | pd.Series, period: int = 14) -> float:
    return float(atr(high, low, close, period).iloc[-1])


def atr_pct_last(high: Iterable[float] | pd.Series, low: Iterable[float] | pd.Series, close: Iterable[float] | pd.Series, period: int = 14) -> float:
    return float(atr_pct(high, low, close, period).iloc[-1])

def macd_hist(series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Совместимость со старым API: вернуть только гистограмму MACD."""
    _, _, hist = macd(series, fast=fast, slow=slow, signal=signal)
    return hist

def macd_hist(series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Совместимость со старым API: вернуть только гистограмму MACD."""
    _, _, hist = macd(series, fast=fast, slow=slow, signal=signal)
    return hist



