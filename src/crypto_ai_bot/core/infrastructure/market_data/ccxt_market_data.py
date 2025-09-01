from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from crypto_ai_bot.core.domain.strategies.base import MarketData as MarketDataPort  # fixed import
from crypto_ai_bot.core.infrastructure.market_data.cache import TTLCache


class CcxtMarketData(MarketDataPort):
    """Рыночные данные через exchange брокера (без двойного подключения)."""

    def __init__(self, *, broker: Any, cache_ttl_sec: float = 30.0) -> None:
        self._broker = broker
        self._cache = TTLCache(ttl_sec=cache_ttl_sec)

    async def get_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> Sequence[tuple[Any, ...]]:
        exch = getattr(self._broker, "exchange", None)
        if exch and hasattr(exch, "fetch_ohlcv"):
            key = ("ohlcv", symbol, timeframe, int(limit))
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]
            data = await exch.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
            self._cache.put(key, data)
            return data  # ccxt returns list[list]; typing: Sequence[tuple[Any, ...]]

        if hasattr(self._broker, "fetch_ohlcv"):
            key = ("ohlcv", symbol, timeframe, int(limit))
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]
            data = await self._broker.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
            self._cache.put(key, data)
            return data  # type: ignore[return-value]
        return []

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        if hasattr(self._broker, "fetch_ticker"):
            key = ("ticker", symbol)
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]
            t = await self._broker.fetch_ticker(symbol)
            self._cache.put(key, t)
            return t  # type: ignore[return-value]
        return {}
