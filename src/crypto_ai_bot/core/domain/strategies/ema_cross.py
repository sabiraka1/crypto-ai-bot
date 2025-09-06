from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext


class EmaCrossStrategy(BaseStrategy):
    """
    EMA crossover c фильтрами спреда/волатильности.
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        threshold_pct: float = 0.1,
        max_spread_pct: float = 0.5,
        use_volatility_filter: bool = True,
        max_volatility_pct: float = 10.0,
        min_volatility_pct: float = 0.0,
    ) -> None:
        assert fast_period > 0 and slow_period > 0 and fast_period < slow_period
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.threshold = dec(threshold_pct) / dec(100)
        self.max_spread = float(max_spread_pct)
        self.use_vol_filter = bool(use_volatility_filter)
        self.max_vol = float(max_volatility_pct)
        self.min_vol = float(min_volatility_pct)

        self._prices: deque[Decimal] = deque(maxlen=slow_period * 2)
        self._ema_fast: Decimal | None = None
        self._ema_slow: Decimal | None = None

    def _update_ema(self, price: Decimal) -> None:
        alpha_f = dec(2) / (dec(self.fast_period) + dec(1))
        alpha_s = dec(2) / (dec(self.slow_period) + dec(1))
        if self._ema_fast is None or self._ema_slow is None:
            if len(self._prices) >= self.slow_period:
                self._ema_fast = sum(list(self._prices)[-self.fast_period:]) / dec(self.fast_period)
                self._ema_slow = sum(list(self._prices)[-self.slow_period:]) / dec(self.slow_period)
            else:
                return
        else:
            self._ema_fast = price * alpha_f + self._ema_fast * (dec(1) - alpha_f)
            self._ema_slow = price * alpha_s + self._ema_slow * (dec(1) - alpha_s)

    def _filters_ok(self, d: dict[str, Any]) -> tuple[bool, str]:
        spread = float(d.get("spread", 0.0))
        if spread > self.max_spread:
            return False, f"high_spread:{spread:.4f}%>{self.max_spread}%"
        if self.use_vol_filter:
            vol = float(d.get("volatility_pct", 0.0))
            if vol > self.max_vol:
                return False, f"high_volatility:{vol:.2f}%>{self.max_vol}%"
            if vol < self.min_vol:
                return False, f"low_volatility:{vol:.2f}%<{self.min_vol}%"
        return True, "ok"

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # используем тикер, если даны в ctx; иначе загрузим
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            d = {"ticker": ticker}
        else:
            d = ctx.data

        last = dec(str(d.get("ticker", {}).get("last", "0")))
        if last <= 0:
            return Decision(action="hold", reason="no_price")

        self._prices.append(last)
        if len(self._prices) < self.slow_period:
            return Decision(action="hold", reason="warming_up")

        self._update_ema(last)
        if self._ema_fast is None or self._ema_slow is None:
            return Decision(action="hold", reason="ema_init")

        ok, why = self._filters_ok(d)
        if not ok:
            return Decision(action="hold", reason=why)

        upper = self._ema_slow * (dec(1) + self.threshold)
        lower = self._ema_slow * (dec(1) - self.threshold)

        if self._ema_fast > upper:
            return Decision(action="buy", confidence=0.6, reason="ema_golden_cross")
        if self._ema_fast < lower:
            return Decision(action="sell", confidence=0.6, reason="ema_death_cross")
        return Decision(action="hold", reason="no_clear_signal")
