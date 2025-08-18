# src/crypto_ai_bot/backtest/strategies/long_only.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from crypto_ai_bot.backtest.engine import Candle

def _ema(prev: float, price: float, period: int) -> float:
    k = 2.0 / (period + 1.0)
    return price * k + prev * (1.0 - k)

@dataclass
class EMACrossLongOnly:
    fast: int = 9
    slow: int = 21
    _ema_fast: Optional[float] = None
    _ema_slow: Optional[float] = None
    _has_long: bool = False

    def on_candle(self, candle: Candle, ctx):
        px = float(candle.close)
        self._ema_fast = px if self._ema_fast is None else _ema(self._ema_fast, px, self.fast)
        self._ema_slow = px if self._ema_slow is None else _ema(self._ema_slow, px, self.slow)

        # пока не прогрелись — ничего не делаем
        if self._ema_fast is None or self._ema_slow is None:
            return None

        # сигнал long-only
        if not self._has_long and self._ema_fast >= self._ema_slow:
            self._has_long = True
            return {"side": "buy"}
        if self._has_long and self._ema_fast < self._ema_slow:
            self._has_long = False
            return {"side": "sell"}
        return None
