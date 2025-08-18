# src/crypto_ai_bot/core/indicators/unified.py
"""
Единый модуль расчёта индикаторов без внешних зависимостей (pandas/ta не требуются).
Все функции принимают списки/кортежи float и возвращают списки той же длины
(с None на префиксе, где данных ещё недостаточно).

Доступно:
- sma(values, period)
- ema(values, period)
- rsi(closes, period=14)         # Wilder
- macd(closes, fast=12, slow=26, signal=9) -> (macd, signal, hist)
- bollinger(closes, period=20, k=2.0) -> (mid, upper, lower)
- compute_all(closes, *, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, bb_period=20, bb_k=2.0)
"""

from math import sqrt
from typing import Iterable, List, Tuple, Optional


Number = float


def _as_list(values: Iterable[Number]) -> List[Number]:
    return list(values)


def sma(values: Iterable[Number], period: int) -> List[Optional[Number]]:
    v = _as_list(values)
    n = len(v)
    out: List[Optional[Number]] = [None] * n
    if period <= 0:
        return out
    s = 0.0
    for i in range(n):
        s += v[i]
        if i >= period:
            s -= v[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(values: Iterable[Number], period: int) -> List[Optional[Number]]:
    v = _as_list(values)
    n = len(v)
    out: List[Optional[Number]] = [None] * n
    if period <= 0:
        return out
    alpha = 2.0 / (period + 1.0)
    s = 0.0
    # первичное значение — SMA(period)
    cnt = 0
    for i in range(n):
        s += v[i]
        cnt += 1
        if cnt == period:
            s /= period
            out[i] = s
            start = i + 1
            break
    else:
        return out  # недостаточно данных
    # сглаживание
    prev = s
    for i in range(start, n):
        prev = alpha * v[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def rsi(closes: Iterable[Number], period: int = 14) -> List[Optional[Number]]:
    c = _as_list(closes)
    n = len(c)
    out: List[Optional[Number]] = [None] * n
    if period <= 0 or n < period + 1:
        return out

    gains = 0.0
    losses = 0.0
    # первые period изменений
    for i in range(1, period + 1):
        ch = c[i] - c[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    rs = (avg_gain / avg_loss) if avg_loss != 0 else float("inf")
    out[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, n):
        ch = c[i] - c[i - 1]
        gain = max(ch, 0.0)
        loss = max(-ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = (avg_gain / avg_loss) if avg_loss != 0 else float("inf")
        out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def macd(
    closes: Iterable[Number],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[List[Optional[Number]], List[Optional[Number]], List[Optional[Number]]]:
    c = _as_list(closes)
    ema_fast = ema(c, fast)
    ema_slow = ema(c, slow)
    n = len(c)
    line: List[Optional[Number]] = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            line[i] = ema_fast[i] - ema_slow[i]
    sig = ema([x if x is not None else 0.0 for x in line], signal)  # ema игнорит префикс None
    hist: List[Optional[Number]] = [None] * n
    for i in range(n):
        if line[i] is not None and sig[i] is not None:
            hist[i] = line[i] - sig[i]
    return line, sig, hist


def bollinger(
    closes: Iterable[Number],
    period: int = 20,
    k: float = 2.0
) -> Tuple[List[Optional[Number]], List[Optional[Number]], List[Optional[Number]]]:
    c = _as_list(closes)
    n = len(c)
    mid = sma(c, period)
    upper: List[Optional[Number]] = [None] * n
    lower: List[Optional[Number]] = [None] * n
    for i in range(n):
        if i >= period - 1 and mid[i] is not None:
            s2 = 0.0
            m = mid[i]
            for j in range(i - period + 1, i + 1):
                d = c[j] - m
                s2 += d * d
            stdev = sqrt(s2 / period)
            upper[i] = m + k * stdev
            lower[i] = m - k * stdev
    return mid, upper, lower


def compute_all(
    closes: Iterable[Number],
    *,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_k: float = 2.0
) -> dict:
    c = _as_list(closes)
    out = {}
    out["rsi"] = rsi(c, rsi_period)
    macd_line, macd_sig, macd_hist = macd(c, macd_fast, macd_slow, macd_signal)
    out["macd"] = macd_line
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist
    mid, up, lo = bollinger(c, bb_period, bb_k)
    out["bb_mid"] = mid
    out["bb_up"] = up
    out["bb_lo"] = lo
    return out
