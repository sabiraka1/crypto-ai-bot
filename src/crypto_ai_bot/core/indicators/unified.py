# src/crypto_ai_bot/core/indicators/unified.py
from __future__ import annotations

"""
Единый источник технических индикаторов для всего проекта.

Только чистые вычисления на pandas/numpy:
 - без IO, без HTTP, без чтения ENV
 - устойчивость к коротким рядам/NaN
 - детерминированность: ewm(..., adjust=False)

Экспортируемые функции:
 - ema(series, n) -> pd.Series
 - rsi(series, n=14) -> pd.Series         # Wilder
 - macd(series, fast=12, slow=26, signal=9) -> (macd, signal, hist)
 - atr(high, low, close, n=14) -> pd.Series
 - atr_last(high, low, close, n=14) -> float | None
 - calculate_all_indicators(df, ...) -> pd.DataFrame  # добавляет стандартный набор колонок
"""

from typing import Iterable, Sequence, Tuple, Optional

import numpy as np
import pandas as pd

__all__ = [
    "ema",
    "rsi",
    "macd",
    "atr",
    "atr_last",
    "calculate_all_indicators",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_series(x: pd.Series | pd.DataFrame | Iterable[float]) -> pd.Series:
    if isinstance(x, pd.Series):
        return x
    if isinstance(x, pd.DataFrame):
        # берем первый столбец
        return x.iloc[:, 0]
    return pd.Series(list(x), dtype="float64")


def _require_series(*arr: Iterable[float]) -> Tuple[pd.Series, ...]:
    return tuple(_as_series(a).astype("float64") for a in arr)  # type: ignore[return-value]


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    TR = max(high-low, |high - prev_close|, |low - prev_close|)
    """
    prev_close = close.shift(1)
    hl = (high - low).abs()
    hc = (high - prev_close).abs()
    lc = (low - prev_close).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr


def _ewm_wilder(s: pd.Series, n: int) -> pd.Series:
    """
    Wilder smoothing эквивалентно ewm(alpha=1/n, adjust=False, min_periods=n).
    """
    if n <= 0:
        raise ValueError("period n must be > 0")
    return s.ewm(alpha=1.0 / float(n), adjust=False, min_periods=n).mean()


def _clip01(x: pd.Series) -> pd.Series:
    return x.clip(lower=0.0, upper=1.0)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def ema(series: Iterable[float], n: int) -> pd.Series:
    """
    Экспоненциальная средняя (EMA) с min_periods=n, adjust=False.
    """
    s = _as_series(series).astype("float64")
    if n <= 0:
        raise ValueError("period n must be > 0")
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(series: Iterable[float], n: int = 14) -> pd.Series:
    """
    RSI по Уайлдеру (Wilder):
      - delta = diff(close)
      - gains = max(delta, 0); losses = max(-delta, 0)
      - avg_gain/avg_loss: Wilder ewm(alpha=1/n)
      - RSI = 100 - 100 / (1 + RS)
    Границы: [0, 100], min_periods=n.
    """
    close = _as_series(series).astype("float64")
    if n <= 0:
        raise ValueError("period n must be > 0")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = _ewm_wilder(gain, n)
    avg_loss = _ewm_wilder(loss, n)

    # RS = avg_gain / avg_loss, аккуратно с нулём
    rs = pd.Series(np.where(avg_loss.to_numpy() == 0.0, np.inf, avg_gain / avg_loss), index=close.index)
    rsi_val = 100.0 - (100.0 / (1.0 + rs))
    # когда и рост, и падение 0 → нейтрально 50
    both_zero = (avg_gain == 0.0) & (avg_loss == 0.0)
    rsi_val = rsi_val.mask(both_zero, 50.0)
    return rsi_val.astype("float64").clip(0.0, 100.0)


def macd(series: Iterable[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD = EMA(fast) - EMA(slow), signal = EMA(MACD, signal), hist = MACD - signal.
    min_periods у EMA = соответствующий период (fast/slow/signal).
    """
    close = _as_series(series).astype("float64")
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("periods must be > 0")
    if fast >= slow:
        # классический MACD требует fast < slow
        raise ValueError("fast must be < slow")

    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = (ema_fast - ema_slow).astype("float64")
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = (macd_line - signal_line).astype("float64")
    return macd_line, signal_line, hist


def atr(high: Iterable[float], low: Iterable[float], close: Iterable[float], n: int = 14) -> pd.Series:
    """
    Average True Range (Wilder). min_periods=n.
    """
    h, l, c = _require_series(high, low, close)
    tr = _true_range(h, l, c)
    return _ewm_wilder(tr, n).astype("float64")


def atr_last(high: Iterable[float], low: Iterable[float], close: Iterable[float], n: int = 14) -> Optional[float]:
    """
    Последнее валидное значение ATR как float, либо None, если данных недостаточно.
    """
    s = atr(high, low, close, n)
    last = s.dropna().iloc[-1:]  # последняя не-NaN
    if len(last) == 0:
        return None
    return float(last.iloc[0])


# ---------------------------------------------------------------------------
# Bulk calculation for a full OHLCV DataFrame
# ---------------------------------------------------------------------------

_OHLCV_ALIASES = {
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c", "price"},
    "volume": {"volume", "v", "vol"},
}


def _find_col(df: pd.DataFrame, logical: str) -> str:
    """
    Находим имя столбца в df по логическому имени (open/high/low/close/volume)
    с учётом возможных алиасов и регистра.
    """
    want = _OHLCV_ALIASES.get(logical, {logical})
    lowmap = {str(c).lower(): c for c in df.columns}
    for cand in want:
        if cand in lowmap:
            return lowmap[cand]
    # если точного алиаса нет — пробуем прямое совпадение без алиаса
    if logical in lowmap:
        return lowmap[logical]
    raise KeyError(f"Required column not found for '{logical}', tried: {sorted(want)}; available: {list(df.columns)}")


def calculate_all_indicators(
    df: pd.DataFrame,
    *,
    ema_periods: Sequence[int] = (20, 50, 200),
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    atr_period: int = 14,
    add_pct: bool = True,
) -> pd.DataFrame:
    """
    Добавляет к DataFrame стандартный набор индикаторов (float64) и возвращает НОВУЮ копию.

    Входной df должен содержать стандартные OHLCV-колонки (в любом регистре/алиасах), например:
      ['time','open','high','low','close','volume']  — time не обязателен

    Добавляемые поля (пример):
      - ema{n}                      (для n из ema_periods)
      - rsi{rsi_period}
      - macd, macd_signal, macd_hist   (classic 12/26/9 по умолчанию)
      - atr{atr_period}
      - atr_pct{atr_period}            (ATR/close * 100), если add_pct=True

    Примечания:
      - min_periods у EMA/ATR/RSI равны их периодам → первые значения будут NaN.
      - Никаких сортировок/перестановок строк не делаем; считаем, что данные уже упорядочены.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")

    out = df.copy()

    # locate columns (сохраняем оригинальные имена)
    col_open = _find_col(out, "open")
    col_high = _find_col(out, "high")
    col_low = _find_col(out, "low")
    col_close = _find_col(out, "close")
    # volume опционален для индикаторов, но если есть — определим имя
    try:
        col_volume = _find_col(out, "volume")
    except Exception:
        col_volume = None  # не критично

    o = out[col_open].astype("float64")
    h = out[col_high].astype("float64")
    l = out[col_low].astype("float64")
    c = out[col_close].astype("float64")

    # EMA
    for n in ema_periods:
        out[f"ema{int(n)}"] = ema(c, int(n)).astype("float64")

    # RSI
    out[f"rsi{int(rsi_period)}"] = rsi(c, int(rsi_period)).astype("float64")

    # MACD
    macd_line, signal_line, hist = macd(c, fast=int(macd_fast), slow=int(macd_slow), signal=int(macd_signal))
    out["macd"] = macd_line.astype("float64")
    out["macd_signal"] = signal_line.astype("float64")
    out["macd_hist"] = hist.astype("float64")

    # ATR
    atr_series = atr(h, l, c, n=int(atr_period))
    out[f"atr{int(atr_period)}"] = atr_series.astype("float64")
    if add_pct:
        with np.errstate(divide="ignore", invalid="ignore"):
            atr_pct = (atr_series / c.replace(0.0, np.nan)) * 100.0
        out[f"atr_pct{int(atr_period)}"] = atr_pct.astype("float64")

    return out
