from __future__ import annotations
from collections.abc import Sequence
from typing import Any, List, Dict, Tuple, cast

from crypto_ai_bot.core.domain.strategies.base import MarketData as MarketData
from crypto_ai_bot.core.infrastructure.market_data.cache import TTLCache

_OHLCV = List[List[Any]]  # ccxt: list[list[number]]
_TICKER = Dict[str, Any]

class CcxtMarketData(MarketData):
    def __init__(self, *, broker: Any, cache_ttl_sec: float = 30.0) -> None:
        self._broker = broker
        self._cache: TTLCache[Any] = TTLCache(ttl_sec=cache_ttl_sec)

    async def get_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> Sequence[Tuple[Any, ...]]:
        key = ("ohlcv", symbol, timeframe, int(limit))
        cached = self._cache.get(key)
        if cached is not None:
            data = cast(_OHLCV, cached)
            return tuple(tuple(r) for r in data)
        # broker.exchange or broker direct
        fetch = None
        if hasattr(self._broker, "exchange") and hasattr(self._broker.exchange, "fetch_ohlcv"):
            fetch = self._broker.exchange.fetch_ohlcv
        elif hasattr(self._broker, "fetch_ohlcv"):
            fetch = self._broker.fetch_ohlcv
        if fetch is None:
            return tuple()
        data = await fetch(symbol, timeframe=timeframe, limit=int(limit))
        self._cache.put(key, data)
        return tuple(tuple(r) for r in cast(_OHLCV, data))

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        key = ("ticker", symbol)
        cached = self._cache.get(key)
        if cached is not None:
            return cast(_TICKER, cached)
        fetch = getattr(self._broker, "fetch_ticker", None)
        if not callable(fetch):
            return {}
        t = await fetch(symbol)
        self._cache.put(key, t)
        return cast(_TICKER, t)
