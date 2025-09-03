from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.domain.strategies.base import BaseStrategy, Decision, MarketData, StrategyContext
from crypto_ai_bot.utils.decimal import dec


def _ema(values: list[Decimal], period: int) -> list[Decimal]:
    if period <= 1 or not values:
        return values[:]
    k = Decimal("2") / Decimal(period + 1)
    out: list[Decimal] = []
    ema_val: Decimal | None = None
    for v in values:
        if ema_val is None:
            ema_val = v
        else:
            ema_val = v * k + ema_val * (Decimal("1") - k)
        out.append(ema_val)
    return out


def _atr(ohlcv: Sequence[tuple[Any, ...]], period: int) -> Decimal:
    # ohlcv: [ (ts, o,h,l,c,v), ... ]
    if len(ohlcv) < max(2, period + 1):
        return dec("0")
    trs: list[Decimal] = []
    prev_close = dec(str(ohlcv[0][4]))
    for _, o, h, l, c, _ in ohlcv[1:]:
        o, h, l, c = map(lambda x: dec(str(x)), (o, h, l, c))
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
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
    )  # ДћВѕДћВіГ‘в‚¬ДћВ°ДћВЅДћВёГ‘вЂЎДћВёГ‘вЂљДћВµДћВ»Г‘Е’ Г‘Л†Г‘Ж’ДћВјДћВ°, 1000% ~ Г‘вЂћДћВ°ДћВєГ‘вЂљДћВёГ‘вЂЎДћВµГ‘ВЃДћВєДћВё ДћВѕГ‘вЂљДћВєДћВ»Г‘ВЋГ‘вЂЎДћВµДћВЅДћВѕ
    ema_min_slope: Decimal = dec(
        "0"
    )  # ДћВјДћВёДћВЅДћВёДћВјДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВ№ ДћВЅДћВ°ДћВєДћВ»ДћВѕДћВЅ (ДћВІ ДћВїГ‘в‚¬ДћВѕГ‘вЂ ДћВµДћВЅГ‘вЂљДћВ°Г‘вЂ¦) ДћВєГ‘в‚¬ДћВ°Г‘вЂљДћВєДћВѕГ‘ВЃГ‘в‚¬ДћВѕГ‘вЂЎДћВЅДћВѕДћВ№ EMA ДћВѕГ‘вЂљДћВЅДћВѕГ‘ВЃДћВёГ‘вЂљДћВµДћВ»Г‘Е’ДћВЅДћВѕ Г‘вЂ ДћВµДћВЅГ‘вЂ№


class EmaAtrStrategy(BaseStrategy):
    """
    ДћЕёГ‘в‚¬ДћВѕГ‘ВЃГ‘вЂљДћВ°Г‘ВЏ ДћВё Г‘вЂЎДћВёГ‘ВЃГ‘вЂљДћВ°Г‘ВЏ Г‘ВЃГ‘вЂљГ‘в‚¬ДћВ°Г‘вЂљДћВµДћВіДћВёГ‘ВЏ:
    - ДћВЎДћВёДћВіДћВЅДћВ°ДћВ» BUY, ДћВєДћВѕДћВіДћВґДћВ° EMA_short > EMA_long ДћВё ДћВєГ‘в‚¬ДћВ°Г‘вЂљДћВєДћВѕГ‘ВЃГ‘в‚¬ДћВѕГ‘вЂЎДћВЅДћВ°Г‘ВЏ EMA ДћВЅДћВµ Г‚В«ДћВїДћВ»ДћВѕГ‘ВЃДћВєДћВ°Г‘ВЏГ‚В» (ДћВЅДћВ°ДћВєДћВ»ДћВѕДћВЅ > ema_min_slope)
    - ДћВЎДћВёДћВіДћВЅДћВ°ДћВ» SELL, ДћВєДћВѕДћВіДћВґДћВ° EMA_short < EMA_long
    - ATR Г‘вЂћДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬: ДћВµГ‘ВЃДћВ»ДћВё ATR% > atr_max_pct Гўв‚¬вЂќ ДћВёДћВіДћВЅДћВѕГ‘в‚¬ДћВёГ‘в‚¬Г‘Ж’ДћВµДћВј (Г‘ВЃДћВ»ДћВёГ‘Л†ДћВєДћВѕДћВј Г‘Л†Г‘Ж’ДћВјДћВЅДћВѕ)
    ДћВ ДћВ°ДћВ·ДћВјДћВµГ‘в‚¬Г‘вЂ№ ДћВЅДћВµ ДћВѕДћВїГ‘в‚¬ДћВµДћВґДћВµДћВ»Г‘ВЏДћВµГ‘вЂљ Гўв‚¬вЂќ ДћВѕГ‘вЂљДћВґДћВ°Г‘вЂГ‘вЂљ Г‘вЂљДћВѕДћВ»Г‘Е’ДћВєДћВѕ ДћВЅДћВ°ДћВїГ‘в‚¬ДћВ°ДћВІДћВ»ДћВµДћВЅДћВЅГ‘вЂ№ДћВ№ Г‘ВЃДћВёДћВіДћВЅДћВ°ДћВ» + reason.
    """

    def __init__(self, cfg: EmaAtrConfig) -> None:
        self.cfg = cfg

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # ДћЕёДћВѕДћВ»Г‘Ж’Г‘вЂЎДћВ°ДћВµДћВј OHLCV ДћВґДћВ°ДћВЅДћВЅГ‘вЂ№ДћВµ
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="1m", limit=300)
        if len(ohlcv) < max(self.cfg.ema_long + 2, self.cfg.atr_period + 2):
            return Decision(action="hold", reason="not_enough_bars")

        closes: list[Decimal] = [dec(str(x[4])) for x in ohlcv]
        ema_s = _ema(closes, self.cfg.ema_short)
        ema_l = _ema(closes, self.cfg.ema_long)
        es, el = ema_s[-1], ema_l[-1]

        # ATR Г‘вЂћДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬ ДћВїДћВѕ ДћВѕГ‘вЂљДћВЅДћВѕГ‘ВЃДћВёГ‘вЂљДћВµДћВ»Г‘Е’ДћВЅДћВѕДћВ№ ДћВІДћВѕДћВ»ДћВ°Г‘вЂљДћВёДћВ»Г‘Е’ДћВЅДћВѕГ‘ВЃГ‘вЂљДћВё (ДћВє Г‘вЂ ДћВµДћВЅДћВµ)
        atr_abs = _atr(ohlcv, self.cfg.atr_period)
        last = closes[-1]
        atr_pct = (atr_abs / last * dec("100")) if last > 0 else dec("0")
        if atr_pct > self.cfg.atr_max_pct:
            return Decision(action="hold", reason=f"atr_too_high:{atr_pct:.2f}%")

        # ДћВќДћВ°ДћВєДћВ»ДћВѕДћВЅ ДћВєГ‘в‚¬ДћВ°Г‘вЂљДћВєДћВѕГ‘ВЃГ‘в‚¬ДћВѕГ‘вЂЎДћВЅДћВѕДћВ№ EMA ДћВѕГ‘вЂљДћВЅДћВѕГ‘ВЃДћВёГ‘вЂљДћВµДћВ»Г‘Е’ДћВЅДћВѕ Г‘вЂ ДћВµДћВЅГ‘вЂ№ (ДћВїГ‘в‚¬ДћВѕГ‘вЂ ДћВµДћВЅГ‘вЂљ)
        if len(ema_s) >= 2:
            slope = (ema_s[-1] - ema_s[-2]) / last * dec("100") if last > 0 else dec("0")
        else:
            slope = dec("0")

        # ДћвЂєДћВѕДћВіДћВёДћВєДћВ° Г‘ВЃДћВёДћВіДћВЅДћВ°ДћВ»ДћВѕДћВІ
        if es > el and slope >= self.cfg.ema_min_slope:
            return Decision(action="buy", confidence=0.6, reason=f"ema_bull;slope={slope:.3f}%")
        if es < el:
            return Decision(action="sell", confidence=0.6, reason="ema_bear")
        return Decision(action="hold", reason="flat_or_low_slope")
