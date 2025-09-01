from typing import Any
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.core.domain.strategies.base import MarketData, BaseStrategy, Decision, StrategyContext  # Исправлен путь
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
    atr_max_pct: Decimal = dec("1000")  # ограничитель шума, 1000% ~ фактически отключено
    ema_min_slope: Decimal = dec("0")   # минимальный наклон (в процентах) краткосрочной EMA относительно цены


class EmaAtrStrategy(BaseStrategy):
    """
    Простая и чистая стратегия:
    - Сигнал BUY, когда EMA_short > EMA_long и краткосрочная EMA не «плоская» (наклон > ema_min_slope)
    - Сигнал SELL, когда EMA_short < EMA_long
    - ATR фильтр: если ATR% > atr_max_pct — игнорируем (слишком шумно)
    Размеры не определяет — отдаёт только направленный сигнал + reason.
    """

    def __init__(self, cfg: EmaAtrConfig) -> None:
        self.cfg = cfg

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # Получаем OHLCV данные
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="1m", limit=300)
        if len(ohlcv) < max(self.cfg.ema_long + 2, self.cfg.atr_period + 2):
            return Decision(action="hold", reason="not_enough_bars")

        closes: list[Decimal] = [dec(str(x[4])) for x in ohlcv]
        ema_s = _ema(closes, self.cfg.ema_short)
        ema_l = _ema(closes, self.cfg.ema_long)
        es, el = ema_s[-1], ema_l[-1]

        # ATR фильтр по относительной волатильности (к цене)
        atr_abs = _atr(ohlcv, self.cfg.atr_period)
        last = closes[-1]
        atr_pct = (atr_abs / last * dec("100")) if last > 0 else dec("0")
        if atr_pct > self.cfg.atr_max_pct:
            return Decision(action="hold", reason=f"atr_too_high:{atr_pct:.2f}%")

        # Наклон краткосрочной EMA относительно цены (процент)
        if len(ema_s) >= 2:
            slope = (ema_s[-1] - ema_s[-2]) / last * dec("100") if last > 0 else dec("0")
        else:
            slope = dec("0")

        # Логика сигналов
        if es > el and slope >= self.cfg.ema_min_slope:
            return Decision(action="buy", confidence=0.6, reason=f"ema_bull;slope={slope:.3f}%")
        if es < el:
            return Decision(action="sell", confidence=0.6, reason="ema_bear")
        return Decision(action="hold", reason="flat_or_low_slope")
