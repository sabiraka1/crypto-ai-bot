from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any, Deque, Dict, Optional, Tuple

from .base import BaseStrategy, StrategyContext, Decision


class EmaCrossStrategy(BaseStrategy):
    """EMA crossover с фильтрами спреда/волатильности.

    По контракту возвращает строку-решение ('buy'|'sell'|'hold') и explain.
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        threshold_pct: float = 0.1,      # 0.1% дивергенция fast/slow
        max_spread_pct: float = 0.5,     # фильтр спреда
        use_volatility_filter: bool = True,
        max_volatility_pct: float = 10.0,
        min_volatility_pct: float = 0.0, # можно задать >0 для «слишком низкая вола»
    ) -> None:
        assert fast_period > 0 and slow_period > 0 and fast_period < slow_period
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.threshold = Decimal(str(threshold_pct)) / Decimal("100")
        self.max_spread = float(max_spread_pct)
        self.use_vol_filter = bool(use_volatility_filter)
        self.max_vol = float(max_volatility_pct)
        self.min_vol = float(min_volatility_pct)

        self._prices: Deque[Decimal] = deque(maxlen=slow_period * 2)
        self._ema_fast: Optional[Decimal] = None
        self._ema_slow: Optional[Decimal] = None

    def _update_ema(self, price: Decimal) -> None:
        """EMA(t) = price*alpha + EMA(t-1)*(1-alpha)"""
        alpha_f = Decimal("2") / (Decimal(self.fast_period) + Decimal("1"))
        alpha_s = Decimal("2") / (Decimal(self.slow_period) + Decimal("1"))

        if self._ema_fast is None or self._ema_slow is None:
            # Инициализация через SMA
            if len(self._prices) >= self.slow_period:
                self._ema_fast = sum(list(self._prices)[-self.fast_period:]) / Decimal(self.fast_period)
                self._ema_slow = sum(list(self._prices)[-self.slow_period:]) / Decimal(self.slow_period)
            else:
                # недостаточно истории для SMA инициализации
                return
        else:
            self._ema_fast = price * alpha_f + self._ema_fast * (Decimal("1") - alpha_f)
            self._ema_slow = price * alpha_s + self._ema_slow * (Decimal("1") - alpha_s)

    def _filters_ok(self, d: Dict[str, Any]) -> Tuple[bool, str]:
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

    def decide(self, ctx: StrategyContext) -> Tuple[Decision, Dict[str, Any]]:
        d = ctx.data
        last = Decimal(str(d.get("ticker", {}).get("last", "0")))
        explain: Dict[str, Any] = {
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

        # История и EMA
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

        # Фильтры
        ok, why = self._filters_ok(d)
        if not ok:
            explain["reason"] = why
            return "hold", explain

        # Сигнал
        upper = self._ema_slow * (Decimal("1") + self.threshold)
        lower = self._ema_slow * (Decimal("1") - self.threshold)

        if self._ema_fast > upper:
            explain["reason"] = "ema_golden_cross"
            return "buy", explain
        if self._ema_fast < lower:
            explain["reason"] = "ema_death_cross"
            return "sell", explain

        explain["reason"] = "no_clear_signal"
        return "hold", explain
