from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec

from .base import BaseStrategy, Decision, StrategyContext, MarketData


class EmaCrossStrategy(BaseStrategy):
    """EMA crossover Ñ Ñ„Ğ¸Ğ»ÑŒÑ‚Ñ€Ğ°Ğ¼Ğ¸ ÑĞ¿Ñ€ĞµĞ´Ğ°/Ğ²Ğ¾Ğ»Ğ°Ñ‚Ğ¸Ğ»ÑŒĞ½Ğ¾ÑÑ‚Ğ¸.

    ĞŸĞ¾ ĞºĞ¾Ğ½Ñ‚Ñ€Ğ°ĞºÑ‚Ñƒ Ğ²Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ ÑÑ‚Ñ€Ğ¾ĞºÑƒ-Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ ('buy'|'sell'|'hold') Ğ¸ explain.
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        threshold_pct: float = 0.1,      # 0.1% Ğ´Ğ¸Ğ²ĞµÑ€Ğ³ĞµĞ½Ñ†Ğ¸Ñ fast/slow
        max_spread_pct: float = 0.5,     # Ñ„Ğ¸Ğ»ÑŒÑ‚Ñ€ ÑĞ¿Ñ€ĞµĞ´Ğ°
        use_volatility_filter: bool = True,
        max_volatility_pct: float = 10.0,
        min_volatility_pct: float = 0.0, # Ğ¼Ğ¾Ğ¶Ğ½Ğ¾ Ğ·Ğ°Ğ´Ğ°Ñ‚ÑŒ >0 Ğ´Ğ»Ñ Â«ÑĞ»Ğ¸ÑˆĞºĞ¾Ğ¼ Ğ½Ğ¸Ğ·ĞºĞ°Ñ Ğ²Ğ¾Ğ»Ğ°Â»
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
        """EMA(t) = price*alpha + EMA(t-1)*(1-alpha)"""
        alpha_f = dec(2) / (dec(self.fast_period) + dec(1))
        alpha_s = dec(2) / (dec(self.slow_period) + dec(1))

        if self._ema_fast is None or self._ema_slow is None:
            # Ğ˜Ğ½Ğ¸Ñ†Ğ¸Ğ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ñ Ñ‡ĞµÑ€ĞµĞ· SMA
            if len(self._prices) >= self.slow_period:
                self._ema_fast = sum(list(self._prices)[-self.fast_period:]) / dec(self.fast_period)
                self._ema_slow = sum(list(self._prices)[-self.slow_period:]) / dec(self.slow_period)
            else:
                # Ğ½ĞµĞ´Ğ¾ÑÑ‚Ğ°Ñ‚Ğ¾Ñ‡Ğ½Ğ¾ Ğ¸ÑÑ‚Ğ¾Ñ€Ğ¸Ğ¸ Ğ´Ğ»Ñ SMA Ğ¸Ğ½Ğ¸Ñ†Ğ¸Ğ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ğ¸
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

    def decide(self, ctx: StrategyContext) -> tuple[str, dict[str, Any]]:
        d = ctx.data or {}
        last = dec(d.get("ticker", {}).get("last", "0"))
        explain: dict[str, Any] = {
            "strategy": "ema_cross",
            "params": {
                "fast": self.fast_period,
                "slow": self.slow_period,
                "threshold_pct": float(self.threshold * 100),
            },
        }
        if last <= 0:
            explain["reason"] = "no_price"
            return "hold", explain

        # Ğ˜ÑÑ‚Ğ¾Ñ€Ğ¸Ñ Ğ¸ EMA
        self._prices.append(last)
        if len(self._prices) < self.slow_period:
            explain["reason"] = "warming_up"
            explain["samples"] = len(self._prices)
            return "hold", explain

        self._update_ema(last)
        if self._ema_fast is None or self._ema_slow is None:
            explain["reason"] = "ema_init"
            return "hold", explain

        explain["indicators"] = {"ema_fast": float(self._ema_fast), "ema_slow": float(self._ema_slow), "price": float(last)}

        # Ğ¤Ğ¸Ğ»ÑŒÑ‚Ñ€Ñ‹
        ok, why = self._filters_ok(d)
        if not ok:
            explain["reason"] = why
            return "hold", explain

        # Ğ¡Ğ¸Ğ³Ğ½Ğ°Ğ»
        upper = self._ema_slow * (dec(1) + self.threshold)
        lower = self._ema_slow * (dec(1) - self.threshold)

        if self._ema_fast > upper:
            explain["reason"] = "ema_golden_cross"
            return "buy", explain
        if self._ema_fast < lower:
            explain["reason"] = "ema_death_cross"
            return "sell", explain

        explain["reason"] = "no_clear_signal"
        return "hold", explain

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        """ĞĞ´Ğ°Ğ¿Ñ‚ĞµÑ€ Ğ´Ğ»Ñ BaseStrategy.generate() - Ğ²Ñ‹Ğ·Ñ‹Ğ²Ğ°ĞµÑ‚ decide() Ğ¸ Ğ¿Ñ€ĞµĞ¾Ğ±Ñ€Ğ°Ğ·ÑƒĞµÑ‚ Ñ€ĞµĞ·ÑƒĞ»ÑŒÑ‚Ğ°Ñ‚."""
        # ĞŸĞ¾Ğ»ÑƒÑ‡Ğ°ĞµĞ¼ Ğ´Ğ°Ğ½Ğ½Ñ‹Ğµ Ğ¸Ğ· MarketData ĞµÑĞ»Ğ¸ Ğ¸Ñ… Ğ½ĞµÑ‚ Ğ² ĞºĞ¾Ğ½Ñ‚ĞµĞºÑÑ‚Ğµ
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            ctx = StrategyContext(
                symbol=ctx.symbol,
                settings=ctx.settings,
                data={"ticker": ticker}
            )
        
        action, explain = self.decide(ctx)
        reason = explain.get("reason", "")
        
        # ĞŸÑ€ĞµĞ¾Ğ±Ñ€Ğ°Ğ·ÑƒĞµĞ¼ Ğ² Decision
        return Decision(
            action=action,
            confidence=0.6,  # ĞœĞ¾Ğ¶Ğ½Ğ¾ Ğ²Ñ‹Ñ‡Ğ¸ÑĞ»ÑÑ‚ÑŒ Ğ½Ğ° Ğ¾ÑĞ½Ğ¾Ğ²Ğµ Ğ¸Ğ½Ğ´Ğ¸ĞºĞ°Ñ‚Ğ¾Ñ€Ğ¾Ğ²
            reason=reason
        )