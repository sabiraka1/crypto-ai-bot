from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    t: int  # ms
    o: float
    h: float
    l: float
    c: float
    v: float


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for x in values[1:]:
        ema = x * k + ema * (1 - k)
    return float(ema)


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    trs = []
    prev_close = candles[0].c
    for c in candles[1:]:
        tr = max(c.h - c.l, abs(c.h - prev_close), abs(prev_close - c.l))
        trs.append(tr)
        prev_close = c.c
    return sum(trs[-period:]) / period if len(trs) >= period else None


def _macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float | None, float | None]:
    if len(values) < slow + signal:
        return None, None

    def ema_list(vals: list[float], p: int) -> list[float]:
        k = 2 / (p + 1)
        out = [vals[0]]
        for x in vals[1:]:
            out.append(x * k + out[-1] * (1 - k))
        return out

    ema_fast = ema_list(values, fast)
    ema_slow = ema_list(values, slow)
    macd_line = [a - b for a, b in zip(ema_fast[-len(ema_slow) :], ema_slow, strict=False)]
    sig = ema_list(macd_line, signal)
    return float(macd_line[-1]), float(sig[-1])


def _bollinger(
    values: list[float], period: int = 20, k: float = 2.0
) -> tuple[float | None, float | None, float | None]:
    if len(values) < period:
        return None, None, None
    import math

    window = values[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = math.sqrt(var)
    upper = mean + k * std
    lower = mean - k * std
    return upper, mean, lower


def last_features(
    ohlcv_15m: Iterable[Candle],
    ohlcv_1h: Iterable[Candle] | None = None,
    ohlcv_4h: Iterable[Candle] | None = None,
    ohlcv_1d: Iterable[Candle] | None = None,
    ohlcv_1w: Iterable[Candle] | None = None,
) -> dict[str, float]:
    c15 = list(ohlcv_15m or [])
    close15 = [c.c for c in c15]
    out: dict[str, float] = {}
    rsi = _rsi(close15, 14) or 0.0
    ema20 = _ema(close15, 20) or (close15[-1] if close15 else 0.0)
    ema50 = _ema(close15, 50) or (close15[-1] if close15 else 0.0)
    macd, macds = _macd(close15) if len(close15) >= 35 else (None, None)
    macd = macd or 0.0
    macds = macds or 0.0
    atr = _atr(c15, 14) or 0.0
    bb_u, bb_m, bb_l = _bollinger(close15, 20, 2.0)
    if bb_u is None:
        bb_u = bb_m = bb_l = 0.0
    out.update(
        {
            "rsi14_15m": float(rsi),
            "ema20_15m": float(ema20),
            "ema50_15m": float(ema50),
            "macd_15m": float(macd),
            "macds_15m": float(macds),
            "atr14_15m": float(atr),
            "bb_u_15m": float(bb_u),
            "bb_m_15m": float(bb_m),
            "bb_l_15m": float(bb_l),
        }
    )

    def tf_snapshot(name: str, candles):
        if not candles:
            out[f"ema20_{name}"] = 0.0
            out[f"ema50_{name}"] = 0.0
            out[f"rsi14_{name}"] = 50.0
            return
        cl = [c.c for c in candles]
        out[f"ema20_{name}"] = float(_ema(cl, 20) or cl[-1])
        out[f"ema50_{name}"] = float(_ema(cl, 50) or cl[-1])
        out[f"rsi14_{name}"] = float(_rsi(cl, 14) or 50.0)

    tf_snapshot("1h", list(ohlcv_1h) if ohlcv_1h else None)
    tf_snapshot("4h", list(ohlcv_4h) if ohlcv_4h else None)
    tf_snapshot("1d", list(ohlcv_1d) if ohlcv_1d else None)
    tf_snapshot("1w", list(ohlcv_1w) if ohlcv_1w else None)
    return out
