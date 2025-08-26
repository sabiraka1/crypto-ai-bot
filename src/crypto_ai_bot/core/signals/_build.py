# src/crypto_ai_bot/core/signals/_build.py
from __future__ import annotations

import math
from collections import deque
from decimal import Decimal, getcontext
from typing import Any, Deque, Dict, Optional

from ..brokers.base import IBroker, TickerDTO
from ..storage.facade import Storage
from ...utils.decimal import dec  # ⬅️ единый хелпер

# Чуть повышаем точность Decimal для безопасной математики
getcontext().prec = 28

# Кольцевой буфер цен по символу (в пределах процесса) — без БД и новых файлов
_PRICES: Dict[str, Deque[Decimal]] = {}
_MAXLEN = 50  # глубина окна для SMA/волы

def _mid_from_ticker(t: TickerDTO) -> Decimal:
    bid = dec(t.bid)
    ask = dec(t.ask)
    last = dec(t.last)
    if bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2")
    return last if last > 0 else (bid or ask)

def _spread_pct(t: TickerDTO, mid: Decimal) -> float:
    bid = dec(t.bid)
    ask = dec(t.ask)
    if bid > 0 and ask > 0 and mid > 0:
        return float(((ask - bid) / mid) * Decimal("100"))
    return 0.0

def _sma(prices: Deque[Decimal], n: int) -> Optional[Decimal]:
    if len(prices) < n or n <= 0:
        return None
    s = sum(list(prices)[-n:], Decimal("0"))
    return (s / Decimal(n))

def _stdev_pct(prices: Deque[Decimal], mid: Decimal, n: int) -> float:
    """Процентная волатильность: stdev(last_n) / mid * 100."""
    if mid <= 0 or len(prices) < n or n <= 1:
        return 0.0
    window = list(prices)[-n:]
    mean = sum(window, Decimal("0")) / Decimal(len(window))
    var = sum((p - mean) * (p - mean) for p in window) / Decimal(len(window))
    stdev = Decimal(str(math.sqrt(float(var))))  # sqrt через float локально
    return float((stdev / mid) * Decimal("100"))

async def build_market_context(
    *,
    symbol: str,
    broker: IBroker,
    storage: Storage,  # зарезервировано под будущее
) -> Dict[str, Any]:
    """
    Собирает рыночный контекст:
      - ticker, mid, spread(%)
      - SMA(5), SMA(20)
      - volatility_pct (stdev_20 / mid * 100)
    """
    t = await broker.fetch_ticker(symbol)
    mid = _mid_from_ticker(t)
    spread = _spread_pct(t, mid)

    ring = _PRICES.get(symbol)
    if ring is None:
        ring = deque(maxlen=_MAXLEN)
        _PRICES[symbol] = ring
    if mid > 0:
        ring.append(mid)

    sma5 = _sma(ring, 5)
    sma20 = _sma(ring, 20)
    vol_pct = _stdev_pct(ring, mid, 20)

    return {
        "ticker": {
            "last": dec(t.last),
            "bid": dec(t.bid),
            "ask": dec(t.ask),
            "mid": mid,
            "timestamp": t.timestamp,
        },
        "spread": spread,           # float, в процентах
        "sma_fast": sma5,          # Decimal | None
        "sma_slow": sma20,         # Decimal | None
        "volatility_pct": vol_pct, # float
        "samples": len(ring),
    }
