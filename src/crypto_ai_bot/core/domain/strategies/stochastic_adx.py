from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


def _dx(ohlcv: Sequence[tuple[Any, ...]], period: int) -> Decimal:
    """
    Приближённый ADX: сначала DX, затем SMA(DX, period)
    """
    if len(ohlcv) < period + 2:
        return dec("0")

    tr_list: list[Decimal] = []
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []

    prev_h = dec(str(ohlcv[0][2]))
    prev_l = dec(str(ohlcv[0][3]))
    prev_c = dec(str(ohlcv[0][4]))

    for _, o, h, l, c, _ in ohlcv[1:]:
        h_d = dec(str(h))
        l_d = dec(str(l))
        c_d = dec(str(c))

        up_move = h_d - prev_h
        down_move = prev_l - l_d
        plus = up_move if (up_move > down_move and up_move > 0) else dec("0")
        minus = down_move if (down_move > up_move and down_move > 0) else dec("0")

        tr = max(h_d - l_d, abs(h_d - prev_c), abs(l_d - prev_c))
        tr_list.append(tr)
        plus_dm.append(plus)
        minus_dm.append(minus)

        prev_h, prev_l, prev_c = h_d, l_d, c_d

    if len(tr_list) < period:
        period = len(tr_list)

    def _sma(xs: list[Decimal]) -> Decimal:
        return sum(xs[-period:]) / dec(str(period)) if xs[-period:] else dec("0")

    tr_s = _sma(tr_list)
    if tr_s == 0:
        return dec("0")
    plus_di = _sma(plus_dm) / tr_s * dec("100")
    minus_di = _sma(minus_dm) / tr_s * dec("100")
    if plus_di + minus_di == 0:
        return dec("0")
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * dec("100")
    return dx  # используем DX как прокси ADX


def _stoch(ohlcv: Sequence[tuple[Any, ...]], k_period: int, d_period: int) -> tuple[Decimal, Decimal]:
    if len(ohlcv) < k_period + d_period:
        return dec("50"), dec("50")
    closes = [dec(str(x[4])) for x in ohlcv]
    highs = [dec(str(x[2])) for x in ohlcv]
    lows = [dec(str(x[3])) for x in ohlcv]

    ks: list[Decimal] = []
    for i in range(k_period - 1, len(closes)):
        window_h = max(highs[i - k_period + 1 : i + 1])
        window_l = min(lows[i - k_period + 1 : i + 1])
        if window_h == window_l:
            ks.append(dec("50"))
        else:
            ks.append((closes[i] - window_l) / (window_h - window_l) * dec("100"))

    def _sma(xs: list[Decimal], p: int) -> Decimal:
        if len(xs) < p:
            return dec("50")
        return sum(xs[-p:]) / dec(str(p))

    k = ks[-1]
    d = _sma(ks, d_period)
    return k, d


class StochasticADXStrategy(BaseStrategy):
    """
    Входы по Stochastic, но только когда «есть тренд» по ADX (DX proxy).
    """

    def __init__(self, k_period: int = 14, d_period: int = 3, adx_period: int = 14, adx_min: float = 18.0):
        self.k_period = int(k_period)
        self.d_period = int(d_period)
        self.adx_period = int(adx_period)
        self.adx_min = dec(str(adx_min))

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="15m", limit=max(120, self.k_period + self.d_period + self.adx_period + 5))
        if len(ohlcv) < self.k_period + self.d_period + self.adx_period:
            return Decision(action="hold", reason="not_enough_bars")

        k, d = _stoch(ohlcv, self.k_period, self.d_period)
        adx = _dx(ohlcv, self.adx_period)

        if adx < self.adx_min:
            return Decision(action="hold", reason="low_trend_strength")

        # сигналы: пересечения K и D
        if k > d and k < dec("40"):  # из перепроданности вверх
            return Decision(action="buy", confidence=0.6, reason="stoch_k_cross_up")
        if k < d and k > dec("60"):  # из перекупленности вниз
            return Decision(action="sell", confidence=0.6, reason="stoch_k_cross_down")
        return Decision(action="hold", reason="stoch_neutral")
