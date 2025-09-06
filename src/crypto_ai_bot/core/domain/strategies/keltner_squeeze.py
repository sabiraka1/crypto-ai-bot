from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


def _ema(values: list[Decimal], period: int) -> list[Decimal]:
    if period <= 1 or not values:
        return values[:]
    k = Decimal("2") / Decimal(period + 1)
    out: list[Decimal] = []
    ema_val: Decimal | None = None
    for v in values:
        ema_val = v if ema_val is None else v * k + ema_val * (Decimal("1") - k)
        out.append(ema_val)
    return out


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


class KeltnerSqueezeStrategy(BaseStrategy):
    """
    «Squeeze» — когда полосы Боллинджера (ширина) меньше канала Кельтнера.
    Вход на выходе из сжатия по направлению пробоя цены относительно EMA.
    """

    def __init__(self, ema_period: int = 20, bb_std: float = 2.0, atr_period: int = 20, keltner_mult: float = 1.5):
        self.ema_period = int(ema_period)
        self.bb_std = dec(str(bb_std))
        self.atr_period = int(atr_period)
        self.kmult = dec(str(keltner_mult))

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="15m", limit=max(200, self.ema_period + self.atr_period + 5))
        if len(ohlcv) < self.ema_period + 5:
            return Decision(action="hold", reason="not_enough_bars")

        closes = [dec(str(x[4])) for x in ohlcv]
        ema = _ema(closes, self.ema_period)[-1]
        last = closes[-1]

        # Bollinger width
        window = closes[-self.ema_period:]
        mean = sum(window) / dec(str(len(window)))
        var = sum((p - mean) * (p - mean) for p in window) / dec(str(len(window)))
        std = dec(str(float(var) ** 0.5))
        bb_upper = mean + std * self.bb_std
        bb_lower = mean - std * self.bb_std
        bb_width = bb_upper - bb_lower

        # Keltner width
        atr = _atr(ohlcv, self.atr_period)
        k_upper = ema + self.kmult * atr
        k_lower = ema - self.kmult * atr
        k_width = k_upper - k_lower

        if bb_width < k_width:
            # в squeeze — ждём выхода: цена покидает bb-диапазон
            if last > bb_upper and last > ema:
                return Decision(action="buy", confidence=0.65, reason="squeeze_breakout_up")
            if last < bb_lower and last < ema:
                return Decision(action="sell", confidence=0.65, reason="squeeze_breakout_down")
            return Decision(action="hold", reason="squeezed_wait_breakout")

        return Decision(action="hold", reason="no_squeeze")
