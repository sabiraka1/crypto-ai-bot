from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MacroContext:
    fear_greed: float | None = None  # 0..100
    btc_dominance: float | None = None  # 0..100
    fed_rate: float | None = None  # e.g. 5.25
    market_trend: float | None = None  # -1..+1 (bear..bull)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def macro_coeff(ctx: MacroContext | None) -> float:
    """Return multiplicative coefficient 0.90..1.10 that *adjusts thresholds*."""
    if ctx is None:
        return 1.0
    coeff = 1.0
    if ctx.fear_greed is not None:
        fg = clamp(ctx.fear_greed, 0.0, 100.0)
        coeff *= 1.0 + (fg - 50.0) / 50.0 * 0.05
    if ctx.btc_dominance is not None:
        dom = clamp(ctx.btc_dominance, 0.0, 100.0)
        coeff *= 1.0 + (dom - 50.0) / 50.0 * 0.02
    if ctx.market_trend is not None:
        mt = clamp(ctx.market_trend, -1.0, 1.0)
        coeff *= 1.0 + mt * 0.05
    if ctx.fed_rate is not None:
        r = ctx.fed_rate
        delta = clamp((r - 3.0) / 3.0, -1.0, 1.0) * 0.03
        coeff *= 1.0 + delta
    return clamp(coeff, 0.90, 1.10)
