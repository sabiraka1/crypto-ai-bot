# src/crypto_ai_bot/core/indicators/unified.py
from __future__ import annotations

"""
Единый векторный набор индикаторов без I/O и без ENV.
Цели:
- Консистентность расчётов во всей системе
- Устойчивость к NaN/коротким рядам
- Совместимость с TradingView/TA-Lib (в пределах безта-lib реализации)
"""

from typing import Tuple

import numpy as np
import pandas as pd

__all__ = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "true_range",
    "atr",
    "atr_last",
    "atr_pct",
    "calculate_all_indicators",
]


# ───────────────────────────── helpers ─────────────────────────────

def _as_series(x: pd.Series | pd.DataFrame | np.ndarray | list | tuple) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.astype(float)
    if isinstance(x, pd.DataFrame):
        # берём первый столбец
        return x.iloc[:, 0].astype(float)
    return pd.Series(x, dtype=float)


def _safe_shift(s: pd.Series, n: int = 1) -> pd.Series:
    return s.shift(n)


def _min_periods(n: int) -> int:
    # Требуем, чтобы первые значения были NaN до накопления окна
    return max(1, int(n))


# ───────────────────────────── базовые индикаторы ─────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    s = _as_series(s)
    return s.rolling(window=n, min_periods=_min_periods(n)).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    """EMA с adjust=False (как в большинстве торговых библиотек)."""
    s = _as_series(s)
    return s.ewm(span=n, adjust=False, min_periods=_min_periods(n)).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """
    RSI по Уайлдеру (Wilder):
      - delta = diff(close)
      - gains = max(delta, 0); losses = max(-delta, 0)
      - smoothed EMA (alpha=1/n) для gains/losses
      - RSI = 100 - 100/(1 + avg_gain/avg_loss)
    """
    s = _as_series(s)
    delta = s.diff()

    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)

    # Уайлдер: alpha = 1/n, adjust=False
    gain = up.ewm(alpha=1.0 / n, adjust=False, min_periods=_min_periods(n)).mean()
    loss = down.ewm(alpha=1.0 / n, adjust=False, min_periods=_min_periods(n)).mean()

    rs = gain / loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)  # нейтральное значение для начальной части


def true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """TR = max( high - low, |high - prev_close|, |low - prev_close| )."""
    h = _as_series(h)
    l = _as_series(l)
    c = _as_series(c)
    pc = _safe_shift(c, 1)
    a = (h - l).abs()
    b = (h - pc).abs()
    d = (l - pc).abs()
    return pd.concat([a, b, d], axis=1).max(axis=1)


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """
    ATR Уайлдера: EMA(TR, alpha=1/n, adjust=False).
    """
    tr = true_range(h, l, c)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=_min_periods(n)).mean()


def atr_last(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> float:
    """Последнее валидное значение ATR (float)."""
    series = atr(h, l, c, n=n)
    last_valid = series.dropna()
    return float(last_valid.iloc[-1]) if not last_valid.empty else 0.0


def atr_pct(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """
    ATR в процентах от close: 100 * ATR / close.
    Если close=0 → NaN (оставляем NaN).
    """
    c = _as_series(c)
    a = atr(h, l, c, n=n)
    return (a / c.replace(0.0, np.nan)) * 100.0


def macd(
    s: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD линия = EMA_fast - EMA_slow
    Signal = EMA(MACD, signal)
    Hist = MACD - Signal
    """
    s = _as_series(s)
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=_min_periods(signal)).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# ───────────────────────────── составная «витрина» ─────────────────────────────

def calculate_all_indicators(
    df: pd.DataFrame,
    *,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_len: int = 14,
    atr_len: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """
    Добавляет в DataFrame следующие столбцы (float64):
      - ema_fast, ema_slow
      - rsi
      - macd, macd_signal, macd_hist
      - atr, atr_pct
    Требуемые входные столбцы: 'open','high','low','close','volume'
    Порядок строк — исходный. Индекс сохраняется.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(map(str.lower, df.columns.astype(str)))
    # допускаем разные кейсы названий столбцов
    cols = {c.lower(): c for c in df.columns}
    if missing:
        # попробуем нормализовать регистр; если всё равно не хватает — бросим KeyError
        if not required.issubset(set(cols.keys())):
            raise KeyError(f"OHLCV columns required: {sorted(required)}; got: {list(df.columns)}")

    o = df[cols.get("open", "open")].astype(float)
    h = df[cols.get("high", "high")].astype(float)
    l = df[cols.get("low", "low")].astype(float)
    c = df[cols.get("close", "close")].astype(float)

    out = df.copy()

    # EMA
    out["ema_fast"] = ema(c, ema_fast).astype(float)
    out["ema_slow"] = ema(c, ema_slow).astype(float)

    # RSI
    out["rsi"] = rsi(c, rsi_len).astype(float)

    # MACD
    macd_line, signal_line, hist = macd(c, macd_fast, macd_slow, macd_signal)
    out["macd"] = macd_line.astype(float)
    out["macd_signal"] = signal_line.astype(float)
    out["macd_hist"] = hist.astype(float)

    # ATR & ATR%
    a = atr(h, l, c, atr_len)
    out["atr"] = a.astype(float)
    out["atr_pct"] = atr_pct(h, l, c, atr_len).astype(float)

    return out
