from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


def _highest_high(ohlcv: Sequence[tuple[Any, ...]], window: int) -> Decimal:
    hi = dec("0")
    for _, o, h, l, c, v in ohlcv[-window:]:
        h_d = dec(str(h))
        if h_d > hi:
            hi = h_d
    return hi


def _lowest_low(ohlcv: Sequence[tuple[Any, ...]], window: int) -> Decimal:
    lo = None
    for _, o, h, l, c, v in ohlcv[-window:]:
        l_d = dec(str(l))
        lo = l_d if lo is None else min(lo, l_d)
    return lo or dec("0")


def _atr(ohlcv: Sequence[tuple[Any, ...]], period: int) -> Decimal:
    if len(ohlcv) < max(2, period + 1):
        return dec("0")
    trs: list[Decimal] = []
    prev_close = dec(str(ohlcv[0][4]))
    for _, o, h, low, c, _ in ohlcv[1:]:
        h_dec = dec(str(h))
        low_dec = dec(str(low))
        c_dec = dec(str(c))
        tr = max(h_dec - low_dec, abs(h_dec - prev_close), abs(low_dec - prev_close))
        trs.append(tr)
        prev_close = c_dec
    if not trs:
        return dec("0")
    if len(trs) < period:
        period = len(trs)
    return sum(trs[-period:]) / dec(str(period))


class DonchianBreakoutStrategy(BaseStrategy):
    """Пробой диапазона N баров + ATR-фильтр (избегаем тонких пробоев)."""

    def __init__(self, channel: int = 20, atr_period: int = 14, atr_min_pct: float = 0.2):
        self.channel = int(channel)
        self.atr_period = int(atr_period)
        self.atr_min_pct = dec(str(atr_min_pct))

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="15m", limit=max(self.channel + 2, self.atr_period + 2))
        if len(ohlcv) < max(self.channel + 1, self.atr_period + 1):
            return Decision(action="hold", reason="not_enough_bars")

        last_close = dec(str(ohlcv[-1][4]))
        hi = _highest_high(ohlcv[:-1], self.channel)  # не включаем текущую
        lo = _lowest_low(ohlcv[:-1], self.channel)

        atr_abs = _atr(ohlcv, self.atr_period)
        atr_pct = (atr_abs / last_close * dec("100")) if last_close > 0 else dec("0")

        if atr_pct < self.atr_min_pct:
            return Decision(action="hold", reason="atr_too_low")

        if last_close > hi:
            return Decision(action="buy", confidence=0.7, reason="donchian_breakout_up")
        if last_close < lo:
            return Decision(action="sell", confidence=0.7, reason="donchian_breakout_down")
        return Decision(action="hold", reason="in_channel")
