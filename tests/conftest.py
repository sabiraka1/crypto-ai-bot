from __future__ import annotations
import asyncio
import types
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

import pytest

# Универсальные генераторы OHLCV
def make_ohlcv_up(n: int, start: float = 100.0, step: float = 1.0, vol: float = 10.0) -> list[tuple[int, float, float, float, float, float]]:
    out = []
    px = start
    for i in range(n):
        o = px
        h = px + step * 1.2
        l = px - step * 0.5
        c = px + step
        v = vol
        out.append((i, o, h, l, c, v))
        px = c
    return out

def make_ohlcv_down(n: int, start: float = 100.0, step: float = 1.0, vol: float = 10.0) -> list[tuple[int, float, float, float, float, float]]:
    out = []
    px = start
    for i in range(n):
        o = px
        h = px + step * 0.5
        l = px - step * 1.2
        c = px - step
        v = vol
        out.append((i, o, h, l, c, v))
        px = c
    return out

def make_ohlcv_range(n: int, center: float = 100.0, amp: float = 1.0, vol: float = 10.0) -> list[tuple[int, float, float, float, float, float]]:
    out = []
    px = center
    sign = 1.0
    for i in range(n):
        delta = amp if (i % 2 == 0) else -amp
        o = px
        h = px + abs(delta) * 1.2
        l = px - abs(delta) * 1.2
        c = px + delta
        v = vol
        out.append((i, o, h, l, c, v))
        px = c
        sign *= -1.0
    return out

class FakeMarketData:
    """
    Минимально достаточный интерфейс под стратегии:
      - get_ohlcv(symbol, timeframe="15m", limit=?)
      - get_ticker(symbol)
    """
    def __init__(self, *, ohlcv_by_tf: dict[str, list[tuple]], last_price: float = 100.0):
        self._by_tf = ohlcv_by_tf
        self._last = last_price

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> list[tuple]:
        data = self._by_tf.get(timeframe, [])
        if limit and len(data) > limit:
            return data[-limit:]
        return data[:]

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "last": float(self._last), "spread": 0.1, "volatility_pct": 2.0}

@dataclass
class FakeSettings:
    STRATEGY_ENABLED: bool = True
    STRATEGY_SET: str = "ema_atr"
    STRATEGY_MODE: str = "first"
    STRATEGY_MIN_CONFIDENCE: float = 0.0
    STRATEGY_WEIGHTS: str | None = None

    # ema_atr параметры (дефолты совпадают с кодом)
    EMA_SHORT: int = 12
    EMA_LONG: int = 26
    ATR_PERIOD: int = 14
    ATR_MAX_PCT: float = 1000.0
    EMA_MIN_SLOPE: float = 0.0

@pytest.fixture
def symbol() -> str:
    return "BTC/USDT"

@pytest.fixture
def md_up() -> FakeMarketData:
    # Для стратегий, которые читают 15m, а иногда 1m (ema_atr использует 1m)
    return FakeMarketData(
        ohlcv_by_tf={
            "15m": make_ohlcv_up(240, start=100.0, step=1.0),
            "1m": make_ohlcv_up(300, start=100.0, step=0.2),
        },
        last_price=140.0,
    )

@pytest.fixture
def md_down() -> FakeMarketData:
    return FakeMarketData(
        ohlcv_by_tf={
            "15m": make_ohlcv_down(240, start=100.0, step=1.0),
            "1m": make_ohlcv_down(300, start=100.0, step=0.2),
        },
        last_price=60.0,
    )

@pytest.fixture
def md_range() -> FakeMarketData:
    return FakeMarketData(
        ohlcv_by_tf={
            "15m": make_ohlcv_range(240, center=100.0, amp=0.6),
            "1m": make_ohlcv_range(300, center=100.0, amp=0.2),
        },
        last_price=100.0,
    )

@pytest.fixture
def settings_default() -> FakeSettings:
    return FakeSettings()
