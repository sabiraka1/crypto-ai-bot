from __future__ import annotations

from decimal import Decimal
from typing import Sequence, Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


def _session_vwap(ohlcv: Sequence[tuple[Any, ...]]) -> Decimal:
    """
    Простой якорный VWAP от начала дня по доступным барам.
    Берём баров ~ N, достаточных для текущей сессии (допущение).
    """
    if not ohlcv:
        return dec("0")
    num = dec("0")
    den = dec("0")
    for _, o, h, l, c, v in ohlcv:
        price = (dec(str(h)) + dec(str(l)) + dec(str(c))) / dec("3")
        vol = dec(str(v)) if v is not None else dec("0")
        num += price * vol
        den += vol
    if den == 0:
        # fallback: среднее цены, если объём отсутствует/недоступен
        return sum((dec(str(x[4])) for x in ohlcv)) / dec(str(len(ohlcv)))
    return num / den


def _zscore(price: Decimal, mean: Decimal, std: Decimal) -> Decimal:
    if std == 0:
        return dec("0")
    return (price - mean) / std


class VWAPReversionStrategy(BaseStrategy):
    """
    Возврат к VWAP: вход при статистически значимом отклонении и возврате.
    """

    def __init__(self, window: int = 96, z_enter: float = 1.0, z_exit: float = 0.3):
        self.window = int(window)  # ~ сутки 15m баров
        self.z_enter = dec(str(z_enter))
        self.z_exit = dec(str(z_exit))

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        ohlcv = await md.get_ohlcv(ctx.symbol, timeframe="15m", limit=max(self.window + 5, 64))
        if len(ohlcv) < self.window:
            return Decision(action="hold", reason="not_enough_bars")

        closes = [dec(str(x[4])) for x in ohlcv]
        last = closes[-1]
        vwap = _session_vwap(ohlcv[-self.window:])

        # отклонение и его «нормальность» по окну
        w = closes[-self.window:]
        mean = sum(w) / dec(str(len(w)))
        var = sum((p - mean) * (p - mean) for p in w) / dec(str(len(w)))
        std = dec(str(float(var) ** 0.5))
        z = _zscore(last, vwap, std)

        # Триггеры: сильное отклонение + возврат к VWAP-уровню
        if last < vwap and abs(z) >= self.z_enter:
            return Decision(action="buy", confidence=0.6, reason=f"below_vwap_z={float(z):.2f}")
        if last > vwap and abs(z) >= self.z_enter:
            return Decision(action="sell", confidence=0.6, reason=f"above_vwap_z={float(z):.2f}")

        # удержание позиции до ослабления сигнала
        if abs(z) <= self.z_exit:
            return Decision(action="hold", reason="z_converged")
        return Decision(action="hold", reason="weak_deviation")
