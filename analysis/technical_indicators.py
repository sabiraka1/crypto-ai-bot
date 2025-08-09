# analysis/technical_indicators.py

import numpy as np
import pandas as pd
from typing import Optional, Tuple

_EPS = 1e-12


def _safe_tail_fill(s: pd.Series) -> pd.Series:
    """
    Заполняет только ХВОСТОВЫЕ NaN последним валидным значением.
    Начальные NaN (из-за минимальных периодов) не трогаем.
    """
    if s is None or s.empty or not s.notna().any():
        return s
    last_valid = s.last_valid_index()
    if last_valid is None:
        return s
    pos = s.index.get_loc(last_valid)
    if isinstance(pos, slice):
        pos = pos.stop - 1
    start = pos + 1
    if start < len(s):
        s = s.copy()
        s.iloc[start:] = s.iloc[start:].fillna(s.iloc[pos])
    return s


def _to_f64(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("float64")


def _ema(s: pd.Series, period: int, minp: int = 1) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=minp).mean().astype("float64")


def _sma(s: pd.Series, period: int, minp: int = 1) -> pd.Series:
    return s.rolling(window=period, min_periods=minp).mean().astype("float64")


def _rsi(close: pd.Series, period: int = 14, minp: int = 1) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    roll_up = gain.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean()
    roll_down = loss.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean()
    rs = roll_up / (roll_down + _EPS)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.astype("float64")


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9, minp: int = 1) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(close, fast, minp)
    ema_slow = _ema(close, slow, minp)
    macd = (ema_fast - ema_slow).astype("float64")
    macd_signal = macd.ewm(span=signal, adjust=False, min_periods=minp).mean().astype("float64")
    macd_hist = (macd - macd_signal).astype("float64")
    return macd, macd_signal, macd_hist, ema_fast, ema_slow


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(window=k_period, min_periods=1).min()
    highest_high = high.rolling(window=k_period, min_periods=1).max()
    rng = (highest_high - lowest_low)
    k = ((close - lowest_low) / (rng.replace(0, np.nan) + _EPS) * 100.0).clip(lower=0.0, upper=100.0)
    d = k.rolling(window=d_period, min_periods=1).mean()
    return k.astype("float64"), d.astype("float64")


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.astype("float64")


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, minp: int = 1) -> pd.Series:
    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean()
    return atr.astype("float64")


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, minp: int = 1) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index, dtype="float64")
    minus_dm = pd.Series(minus_dm, index=high.index, dtype="float64")

    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean()

    plus_di = 100.0 * (plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean() / (atr + _EPS))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean() / (atr + _EPS))
    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + _EPS)).astype("float64")
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=minp).mean()
    return adx.astype("float64")


def _bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std(ddof=0).fillna(0.0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid.astype("float64"), upper.astype("float64"), lower.astype("float64")


def _volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    v_sma = volume.rolling(window=period, min_periods=1).mean()
    return (volume / (v_sma + _EPS)).astype("float64")


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Расчёт индикаторов (без TA-lib). Требуются: open, high, low, close, volume, индекс — DatetimeIndex (UTC).
    Возвращает df с колонками (float64):
      rsi, macd, macd_signal, macd_hist,
      ema_fast(12), ema_slow(26), ema_200,
      sma_50, sma_200,
      stoch_k, stoch_d,
      adx, bb_mid, bb_upper, bb_lower,
      atr, volume_ratio
    На коротких сериях считает максимум возможного. Хвостовые NaN заполняются.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        # не падаем — просто работаем как есть
        pass

    required = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required.issubset(df.columns):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    out = df.copy()
    # сортируем по времени на всякий случай
    try:
        out = out.sort_index()
    except Exception:
        pass

    # типы
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = _to_f64(out[c])

    close = out["close"]; high = out["high"]; low = out["low"]; volume = out["volume"]

    # RSI
    out["rsi"] = _safe_tail_fill(_rsi(close, 14, minp=1))

    # MACD + EMAs
    macd, macd_sig, macd_hist, ema_fast, ema_slow = _macd(close, 12, 26, 9, minp=1)
    out["macd"] = _safe_tail_fill(macd)
    out["macd_signal"] = _safe_tail_fill(macd_sig)
    out["macd_hist"] = _safe_tail_fill(macd_hist)
    out["ema_fast"] = _safe_tail_fill(ema_fast)
    out["ema_slow"] = _safe_tail_fill(ema_slow)

    # EMA 200 / SMA 50 / SMA 200
    out["ema_200"] = _safe_tail_fill(_ema(close, 200, minp=1))
    out["sma_50"] = _safe_tail_fill(_sma(close, 50, minp=1))
    out["sma_200"] = _safe_tail_fill(_sma(close, 200, minp=1))

    # Stochastic
    st_k, st_d = _stochastic(high, low, close, 14, 3)
    out["stoch_k"] = _safe_tail_fill(st_k)
    out["stoch_d"] = _safe_tail_fill(st_d)

    # ADX
    out["adx"] = _safe_tail_fill(_adx(high, low, close, 14, minp=1))

    # Bollinger Bands
    bb_mid, bb_upper, bb_lower = _bollinger(close, 20, 2.0)
    out["bb_mid"] = _safe_tail_fill(bb_mid)
    out["bb_upper"] = _safe_tail_fill(bb_upper)
    out["bb_lower"] = _safe_tail_fill(bb_lower)

    # (опционально) позиция внутри полос Боллинджера — часто нужна для фичей
    try:
        rng = (out["bb_upper"] - out["bb_lower"])
        out["bb_position"] = ((close - out["bb_lower"]) / (rng + _EPS)).clip(0.0, 1.0).astype("float64")
    except Exception:
        pass  # не критично

    # ATR
    out["atr"] = _safe_tail_fill(_atr(high, low, close, 14, minp=1))

    # Volume ratio
    out["volume_ratio"] = _safe_tail_fill(_volume_ratio(volume, 20))

    # гарантируем float64 для всех новых колонок
    new_cols = [
        "rsi", "macd", "macd_signal", "macd_hist",
        "ema_fast", "ema_slow", "ema_200",
        "sma_50", "sma_200",
        "stoch_k", "stoch_d",
        "adx", "bb_mid", "bb_upper", "bb_lower",
        "atr", "volume_ratio", "bb_position"
    ]
    for c in new_cols:
        if c in out.columns:
            out[c] = _to_f64(out[c])

    return out
