from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.domain.strategies.base import (
    BaseStrategy,
    Decision,
    MarketData,
    StrategyContext,
)
from crypto_ai_bot.utils.decimal import dec


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
    # ohlcv: [ (ts, o,h,l,c,v), ... ]
    if len(ohlcv) < max(2, period + 1):
        return dec("0")
    trs: list[Decimal] = []
    prev_close = dec(str(ohlcv[0][4]))
    for _, o, h, low, c, _ in ohlcv[1:]:
        o_dec = dec(str(o))
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


@dataclass
class EmaAtrConfig:
    ema_short: int = 12
    ema_long: int = 26
    atr_period: int = 14
    atr_max_pct: Decimal = dec(
        "1000"
    )  # Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡Ğ¸Ñ‚ĞµĞ»ÑŒ ÑˆÑƒĞ¼Ğ°, 1000% ~ Ñ„Ğ°ĞºÑ‚Ğ¸Ñ‡ĞµÑĞºĞ¸ Ğ¾Ñ‚ĞºĞ»ÑÑ‡ĞµĞ½
    ema_min_slope: Decimal = dec(
        "0"
    )  # Ğ¼Ğ¸Ğ½Ğ¸Ğ¼Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¹ Ğ½Ğ°ĞºĞ»Ğ¾Ğ½ (Ğ² Ğ¿Ñ€Ğ¾Ñ†ĞµĞ½Ñ‚Ğ°Ñ…) ĞºÑ€Ğ°Ñ‚ĞºĞ¾ÑÑ€Ğ¾Ñ‡Ğ½Ğ¾Ğ¹ EMA Ğ¾Ñ‚Ğ½Ğ¾ÑĞ¸Ñ‚ĞµĞ»ÑŒĞ½Ğ¾ Ñ†ĞµĞ½Ñ‹


class EmaAtrStrategy(BaseStrategy):
    """
    ĞŸÑ€Ğ¾ÑÑ‚Ğ°Ñ Ğ¸ Ñ‡Ğ¸ÑÑ‚Ğ°Ñ ÑÑ‚Ñ€Ğ°Ñ‚ĞµĞ³Ğ¸Ñ:
    - Ğ¡Ğ¸Ğ³Ğ½Ğ°Ğ» BUY, ĞºĞ¾Ğ³Ğ´Ğ° EMA_short > EMA_long Ğ¸ ĞºÑ€Ğ°Ñ‚ĞºĞ¾ÑÑ€Ğ¾Ñ‡Ğ½Ğ°Ñ EMA Ğ½Ğµ "Ğ¿Ğ»Ğ¾ÑĞºĞ°Ñ" (Ğ½Ğ°ĞºĞ»Ğ¾Ğ½ > ema_min_slope)
    - Ğ¡Ğ¸Ğ³Ğ½Ğ°Ğ» SELL, ĞºĞ¾Ğ³Ğ´Ğ° EMA_short < EMA_long
    - ATR Ñ„Ğ¸Ğ»ÑŒÑ‚Ñ€: ĞµÑĞ»Ğ¸ ATR% > atr_max_pct â†’ Ğ¸Ğ³Ğ½Ğ¾Ñ€Ğ¸Ñ€ÑƒĞµĞ¼ (ÑĞ»Ğ¸ÑˆĞºĞ¾Ğ¼ ÑˆÑƒĞ¼Ğ½Ğ¾)
    Ğ Ğ°Ğ·Ğ¼ĞµÑ€ Ğ½Ğµ Ğ¾Ğ¿Ñ€ĞµĞ´ĞµĞ»ÑĞµÑ‚ â†’ Ğ¾Ñ‚Ğ´Ğ°Ñ‘Ñ‚ Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ Ğ½Ğ°Ğ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¸Ğµ + reason.
    """

    def __init__(self, cfg: EmaAtrConfig) -> None:
        self.cfg = cfg

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # ĞŸĞ¾Ğ»ÑƒÑ‡Ğ°ĞµĞ¼ OHLCV Ğ´Ğ°Ğ½Ğ½Ñ‹Ğµ
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="1m", limit=300)
        if len(ohlcv) < max(self.cfg.ema_long + 2, self.cfg.atr_period + 2):
            return Decision(action="hold", reason="not_enough_bars")

        closes: list[Decimal] = [dec(str(x[4])) for x in ohlcv]
        ema_s = _ema(closes, self.cfg.ema_short)
        ema_long = _ema(closes, self.cfg.ema_long)
        es, el = ema_s[-1], ema_long[-1]

        # ATR Ñ„Ğ¸Ğ»ÑŒÑ‚Ñ€ Ğ¿Ğ¾ Ğ¾Ñ‚Ğ½Ğ¾ÑĞ¸Ñ‚ĞµĞ»ÑŒĞ½Ğ¾Ğ¹ Ğ²Ğ¾Ğ»Ğ°Ñ‚Ğ¸Ğ»ÑŒĞ½Ğ¾ÑÑ‚Ğ¸ (Ğº Ñ†ĞµĞ½Ğµ)
        atr_abs = _atr(ohlcv, self.cfg.atr_period)
        last = closes[-1]
        atr_pct = (atr_abs / last * dec("100")) if last > 0 else dec("0")
        if atr_pct > self.cfg.atr_max_pct:
            return Decision(action="hold", reason=f"atr_too_high:{atr_pct:.2f}%")

        # ĞĞ°ĞºĞ»Ğ¾Ğ½ ĞºÑ€Ğ°Ñ‚ĞºĞ¾ÑÑ€Ğ¾Ñ‡Ğ½Ğ¾Ğ¹ EMA Ğ¾Ñ‚Ğ½Ğ¾ÑĞ¸Ñ‚ĞµĞ»ÑŒĞ½Ğ¾ Ñ†ĞµĞ½Ñ‹ (Ğ¿Ñ€Ğ¾Ñ†ĞµĞ½Ñ‚)
        slope = (
            ((ema_s[-1] - ema_s[-2]) / last * dec("100") if last > 0 else dec("0"))
            if len(ema_s) >= 2
            else dec("0")
        )

        # Ğ›Ğ¾Ğ³Ğ¸ĞºĞ° ÑĞ¸Ğ³Ğ½Ğ°Ğ»Ğ¾Ğ²
        if es > el and slope >= self.cfg.ema_min_slope:
            return Decision(action="buy", confidence=0.6, reason=f"ema_bull;slope={slope:.3f}%")
        if es < el:
            return Decision(action="sell", confidence=0.6, reason="ema_bear")
        return Decision(action="hold", reason="flat_or_low_slope")
