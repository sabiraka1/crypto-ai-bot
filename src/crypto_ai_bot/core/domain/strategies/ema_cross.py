from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec

from .base import BaseStrategy, Decision, MarketData, StrategyContext


class EmaCrossStrategy(BaseStrategy):
    """EMA crossover Г‘ВЃ Г‘вЂћДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬ДћВ°ДћВјДћВё Г‘ВЃДћВїГ‘в‚¬ДћВµДћВґДћВ°/ДћВІДћВѕДћВ»ДћВ°Г‘вЂљДћВёДћВ»Г‘Е’ДћВЅДћВѕГ‘ВЃГ‘вЂљДћВё.

    ДћЕёДћВѕ ДћВєДћВѕДћВЅГ‘вЂљГ‘в‚¬ДћВ°ДћВєГ‘вЂљГ‘Ж’ ДћВІДћВѕДћВ·ДћВІГ‘в‚¬ДћВ°Г‘вЂ°ДћВ°ДћВµГ‘вЂљ Г‘ВЃГ‘вЂљГ‘в‚¬ДћВѕДћВєГ‘Ж’-Г‘в‚¬ДћВµГ‘Л†ДћВµДћВЅДћВёДћВµ ('buy'|'sell'|'hold') ДћВё explain.
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        threshold_pct: float = 0.1,  # 0.1% ДћВґДћВёДћВІДћВµГ‘в‚¬ДћВіДћВµДћВЅГ‘вЂ ДћВёГ‘ВЏ fast/slow
        max_spread_pct: float = 0.5,  # Г‘вЂћДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬ Г‘ВЃДћВїГ‘в‚¬ДћВµДћВґДћВ°
        use_volatility_filter: bool = True,
        max_volatility_pct: float = 10.0,
        min_volatility_pct: float = 0.0,  # ДћВјДћВѕДћВ¶ДћВЅДћВѕ ДћВ·ДћВ°ДћВґДћВ°Г‘вЂљГ‘Е’ >0 ДћВґДћВ»Г‘ВЏ Г‚В«Г‘ВЃДћВ»ДћВёГ‘Л†ДћВєДћВѕДћВј ДћВЅДћВёДћВ·ДћВєДћВ°Г‘ВЏ ДћВІДћВѕДћВ»ДћВ°Г‚В»
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
            # ДћЛњДћВЅДћВёГ‘вЂ ДћВёДћВ°ДћВ»ДћВёДћВ·ДћВ°Г‘вЂ ДћВёГ‘ВЏ Г‘вЂЎДћВµГ‘в‚¬ДћВµДћВ· SMA
            if len(self._prices) >= self.slow_period:
                self._ema_fast = sum(list(self._prices)[-self.fast_period :]) / dec(self.fast_period)
                self._ema_slow = sum(list(self._prices)[-self.slow_period :]) / dec(self.slow_period)
            else:
                # ДћВЅДћВµДћВґДћВѕГ‘ВЃГ‘вЂљДћВ°Г‘вЂљДћВѕГ‘вЂЎДћВЅДћВѕ ДћВёГ‘ВЃГ‘вЂљДћВѕГ‘в‚¬ДћВёДћВё ДћВґДћВ»Г‘ВЏ SMA ДћВёДћВЅДћВёГ‘вЂ ДћВёДћВ°ДћВ»ДћВёДћВ·ДћВ°Г‘вЂ ДћВёДћВё
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

        # ДћЛњГ‘ВЃГ‘вЂљДћВѕГ‘в‚¬ДћВёГ‘ВЏ ДћВё EMA
        self._prices.append(last)
        if len(self._prices) < self.slow_period:
            explain["reason"] = "warming_up"
            explain["samples"] = len(self._prices)
            return "hold", explain

        self._update_ema(last)
        if self._ema_fast is None or self._ema_slow is None:
            explain["reason"] = "ema_init"
            return "hold", explain

        explain["indicators"] = {
            "ema_fast": float(self._ema_fast),
            "ema_slow": float(self._ema_slow),
            "price": float(last),
        }

        # ДћВ¤ДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬Г‘вЂ№
        ok, why = self._filters_ok(d)
        if not ok:
            explain["reason"] = why
            return "hold", explain

        # ДћВЎДћВёДћВіДћВЅДћВ°ДћВ»
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
        """ДћВђДћВґДћВ°ДћВїГ‘вЂљДћВµГ‘в‚¬ ДћВґДћВ»Г‘ВЏ BaseStrategy.generate() - ДћВІГ‘вЂ№ДћВ·Г‘вЂ№ДћВІДћВ°ДћВµГ‘вЂљ decide() ДћВё ДћВїГ‘в‚¬ДћВµДћВѕДћВ±Г‘в‚¬ДћВ°ДћВ·Г‘Ж’ДћВµГ‘вЂљ Г‘в‚¬ДћВµДћВ·Г‘Ж’ДћВ»Г‘Е’Г‘вЂљДћВ°Г‘вЂљ."""
        # ДћЕёДћВѕДћВ»Г‘Ж’Г‘вЂЎДћВ°ДћВµДћВј ДћВґДћВ°ДћВЅДћВЅГ‘вЂ№ДћВµ ДћВёДћВ· MarketData ДћВµГ‘ВЃДћВ»ДћВё ДћВёГ‘вЂ¦ ДћВЅДћВµГ‘вЂљ ДћВІ ДћВєДћВѕДћВЅГ‘вЂљДћВµДћВєГ‘ВЃГ‘вЂљДћВµ
        if ctx.data is None:
            ticker = await md.get_ticker(ctx.symbol)
            ctx = StrategyContext(symbol=ctx.symbol, settings=ctx.settings, data={"ticker": ticker})

        action, explain = self.decide(ctx)
        reason = explain.get("reason", "")

        # ДћЕёГ‘в‚¬ДћВµДћВѕДћВ±Г‘в‚¬ДћВ°ДћВ·Г‘Ж’ДћВµДћВј ДћВІ Decision
        return Decision(
            action=action,
            confidence=0.6,  # ДћЕ“ДћВѕДћВ¶ДћВЅДћВѕ ДћВІГ‘вЂ№Г‘вЂЎДћВёГ‘ВЃДћВ»Г‘ВЏГ‘вЂљГ‘Е’ ДћВЅДћВ° ДћВѕГ‘ВЃДћВЅДћВѕДћВІДћВµ ДћВёДћВЅДћВґДћВёДћВєДћВ°Г‘вЂљДћВѕГ‘в‚¬ДћВѕДћВІ
            reason=reason,
        )
