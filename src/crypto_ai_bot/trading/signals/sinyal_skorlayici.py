# src/crypto_ai_bot/trading/signals/sinyal_skorlayici.py
from __future__ import annotations

import math
from typing import Dict, Any

import numpy as np
import pandas as pd

try:
    # Пытаемся использовать единый набор индикаторов
    from crypto_ai_bot.core.indicators import unified as I  # type: ignore
except Exception:
    I = None  # fallback ниже


# -------------------- Fallback-индикаторы (локально, только если нет unified) --------------------
def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = (delta.clip(lower=0)).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / (down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# -------------------- Хелперы --------------------
def _last(x: pd.Series | None) -> float | None:
    if x is None or len(x) == 0:
        return None
    v = x.iloc[-1]
    try:
        fv = float(v)
    except Exception:
        return None
    if math.isfinite(fv):
        return fv
    return None

def _safe_ema(series: pd.Series, period: int) -> pd.Series:
    if I and hasattr(I, "ema"):
        return I.ema(series, period)  # type: ignore[attr-defined]
    return _ema(series, period)

def _safe_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    if I and hasattr(I, "rsi"):
        return I.rsi(series, period)  # type: ignore[attr-defined]
    return _rsi(series, period)

def _safe_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    if I and hasattr(I, "macd"):
        return I.macd(series, fast, slow, signal)  # type: ignore[attr-defined]
    return _macd(series, fast, slow, signal)

def _safe_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if I and hasattr(I, "atr"):
        return I.atr(df, period)  # type: ignore[attr-defined]
    return _atr(df, period)


# -------------------- Публичный API --------------------
def aggregate_features(df: pd.DataFrame, settings) -> Dict[str, Any]:
    """
    Единый сбор фич без зависимости от calculate_all_indicators.
    Возвращает минимум, чтобы принимать решение:
      - ema_fast / ema_slow (по close)
      - rsi14
      - macd_hist
      - atr
    """
    close = df["close"].astype(float)

    ema_fast = _safe_ema(close, getattr(settings, "EMA_FAST", 12))
    ema_slow = _safe_ema(close, getattr(settings, "EMA_SLOW", 26))
    rsi14 = _safe_rsi(close, getattr(settings, "RSI_PERIOD", 14))
    _, _, macd_hist = _safe_macd(
        close,
        getattr(settings, "MACD_FAST", 12),
        getattr(settings, "MACD_SLOW", 26),
        getattr(settings, "MACD_SIGNAL", 9),
    )
    atr_s = _safe_atr(df, getattr(settings, "ATR_PERIOD", 14))

    feats = {
        "ema_fast": _last(ema_fast),
        "ema_slow": _last(ema_slow),
        "rsi14": _last(rsi14),
        "macd_hist": _last(macd_hist),
        "atr": _last(atr_s),
    }
    return feats


def validate_features(features: Dict[str, Any], *_args, **_kwargs) -> Dict[str, Any]:
    """
    Простейшая валидация: убираем None/NaN и оставляем только числовые значения.
    Сигнатура гибкая для обратной совместимости.
    """
    out: Dict[str, Any] = {}
    for k, v in features.items():
        try:
            fv = float(v)
            if math.isfinite(fv):
                out[k] = fv
        except Exception:
            continue
    return out
