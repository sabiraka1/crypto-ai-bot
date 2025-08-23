from __future__ import annotations

import math
from collections import deque
from decimal import Decimal, getcontext
from typing import Any, Deque, Dict, Optional

from ..brokers.base import IBroker, TickerDTO
from ..storage.facade import Storage

# Чуть повышаем точность Decimal для безопасной математики
getcontext().prec = 28

# Кольцевой буфер цен по символу (в пределах процесса) — без новых файлов/таблиц
_PRICES: Dict[str, Deque[Decimal]] = {}
_MAXLEN = 50  # глубина окна для SMA/волы (не выносим в ENV по твоему требованию)

def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def _mid_from_ticker(t: TickerDTO) -> Decimal:
    bid = _dec(t.bid)
    ask = _dec(t.ask)
    last = _dec(t.last)
    if bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2")
    return last if last > 0 else (bid or ask)

def _spread_pct(t: TickerDTO, mid: Decimal) -> float:
    bid = _dec(t.bid)
    ask = _dec(t.ask)
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
    # sqrt только через float (внутри локально), дальше возвращаем float %
    stdev = Decimal(str(math.sqrt(float(var))))
    return float((stdev / mid) * Decimal("100"))

async def build_market_context(
    *,
    symbol: str,
    broker: IBroker,
    storage: Storage,  # пока не используем здесь, но оставляем сигнатуру под будущее
) -> Dict[str, Any]:
    """
    Собирает рыночный контекст для принятия решения:
      - ticker, mid, spread(%)
      - SMA(5), SMA(20)
      - volatility_pct (stdev_20 / mid * 100)
    Без внешних зависимостей и без новых файлов.
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
            "last": _dec(t.last),
            "bid": _dec(t.bid),
            "ask": _dec(t.ask),
            "mid": mid,
            "timestamp": t.timestamp,
        },
        "spread": spread,                 # float, в процентах
        "sma_fast": sma5,                # Decimal | None
        "sma_slow": sma20,               # Decimal | None
        "volatility_pct": vol_pct,       # float
        "samples": len(ring),
    }
