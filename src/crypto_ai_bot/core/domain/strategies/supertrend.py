from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


def _atr(ohlcv: Sequence[tuple[Any, ...]], period: int) -> Decimal:
    if len(ohlcv) < max(2, period + 1):
        return dec("0")
    trs: list[Decimal] = []
    prev_close = dec(str(ohlcv[0][4]))
    for _, o, h, l, c, _ in ohlcv[1:]:
        h_d = dec(str(h))
        l_d = dec(str(l))
        c_d = dec(str(c))
        tr = max(h_d - l_d, abs(h_d - prev_close), abs(l_d - prev_close))
        trs.append(tr)
        prev_close = c_d
    if len(trs) < period:
        period = len(trs)
    return sum(trs[-period:]) / dec(str(period))


class SupertrendStrategy(BaseStrategy):
    """
    Классический Supertrend (ATR-бэйзлайн). Flip buy/sell при смене стороны.
    """

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0):
        self.atr_period = int(atr_period)
        self.multiplier = dec(str(multiplier))
        # кеш последних линий
        self._last_trend: str | None = None

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="15m", limit=max(200, self.atr_period + 3))
        if len(ohlcv) < self.atr_period + 3:
            return Decision(action="hold", reason="not_enough_bars")

        atr = _atr(ohlcv, self.atr_period)
        last_o, last_h, last_l, last_c = map(lambda x: dec(str(x)), ohlcv[-1][1:5])

        basic_upper = last_c + self.multiplier * atr
        basic_lower = last_c - self.multiplier * atr

        # простая логика flip: цена выше предыдущего нижнего — тренд бычий, ниже предыдущего верхнего — медвежий
        # для стабильности используем последний close
        trend = "bull" if last_c > basic_lower else ("bear" if last_c < basic_upper else (self._last_trend or "neutral"))
        self._last_trend = trend

        if trend == "bull":
            return Decision(action="buy", confidence=0.6, reason="supertrend_bull")
        if trend == "bear":
            return Decision(action="sell", confidence=0.6, reason="supertrend_bear")
        return Decision(action="hold", reason="supertrend_neutral")
