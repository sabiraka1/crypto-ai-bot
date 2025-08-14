# -*- coding: utf-8 -*-
"""
Lightweight technical indicators used across the project.
Path: src/crypto_ai_bot/analysis/indicators.py
No pandas required; works with list/np.ndarray.
"""
from __future__ import annotations

from typing import Sequence, Tuple
import math

def _as_float_list(x: Sequence[float]) -> list[float]:
    return [float(v) for v in x]

def ema(values: Sequence[float], period: int) -> list[float]:
    vals = _as_float_list(values)
    if period <= 1 or len(vals) == 0:
        return vals[:]
    alpha = 2.0 / (period + 1.0)
    out = []
    s = vals[0]
    out.append(s)
    for v in vals[1:]:
        s = alpha * v + (1.0 - alpha) * s
        out.append(s)
    return out

def sma(values: Sequence[float], period: int) -> list[float]:
    vals = _as_float_list(values)
    out = []
    acc = 0.0
    q = []
    for v in vals:
        q.append(v)
        acc += v
        if len(q) > period:
            acc -= q.pop(0)
        out.append(acc / len(q))
    return out

def rsi(closes: Sequence[float], period: int = 14) -> list[float]:
    c = _as_float_list(closes)
    if len(c) < 2:
        return [50.0 for _ in c]
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(c)):
        d = c[i] - c[i-1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sma(gains, period)
    avg_loss = sma(losses, period)
    rs_list = []
    for g, l in zip(avg_gain, avg_loss):
        if l == 0:
            rs = float('inf')
        else:
            rs = g / l
        rs_list.append(rs)
    out = []
    for rs in rs_list:
        if math.isinf(rs):
            out.append(100.0)
        else:
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out

def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    c = _as_float_list(closes)
    ema_fast = ema(c, fast)
    ema_slow = ema(c, slow)
    macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist

def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    h = _as_float_list(highs)
    l = _as_float_list(lows)
    c = _as_float_list(closes)
    out = []
    prev_close = c[0] if c else 0.0
    for i in range(len(c)):
        tr = max(h[i] - l[i], abs(h[i] - prev_close), abs(l[i] - prev_close))
        out.append(tr)
        prev_close = c[i]
    return out

def atr_wilder(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> list[float]:
    tr = true_range(highs, lows, closes)
    # Wilder's smoothing == EMA with alpha = 1/period
    out = []
    if not tr:
        return out
    s = tr[0]
    out.append(s)
    alpha = 1.0 / float(max(1, period))
    for v in tr[1:]:
        s = alpha * v + (1.0 - alpha) * s
        out.append(s)
    return out

def atr_ewm(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> list[float]:
    # classic EMA-based ATR (alpha = 2/(n+1))
    tr = true_range(highs, lows, closes)
    return ema(tr, period)

def get_unified_atr(method: str, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> list[float]:
    """
    Unified ATR entry point; method: 'ewm' | 'wilder'.
    """
    m = (method or "ewm").lower()
    if m == "wilder":
        return atr_wilder(highs, lows, closes, period)
    # default
    return atr_ewm(highs, lows, closes, period)
