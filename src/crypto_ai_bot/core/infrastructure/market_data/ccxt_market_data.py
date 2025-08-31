from __future__ import annotations

from typing import Any, Sequence, Tuple, Dict

from crypto_ai_bot.core.domain.strategy.base import MarketDataPort
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker  # или ваш адаптер
from crypto_ai_bot.core.infrastructure.brokers.paper_adapter import PaperBroker  # если есть
from crypto_ai_bot.core.infrastructure.market_data.cache import TTLCache


class CcxtMarketData(MarketDataPort):
    """
    Источник рыночных данных, использующий тот же exchange, что и брокер.
    Без дополнительной авторизации и без дублирования коннектов.
    """

    def __init__(self, *, broker: Any, cache_ttl_sec: float = 30.0) -> None:
        self._broker = broker
        self._cache = TTLCache(ttl_sec=cache_ttl_sec)

    async def get_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> Sequence[tuple]:
        exch = getattr(self._broker, "exchange", None)
        if exch and hasattr(exch, "fetch_ohlcv"):
            # ccxt обычно отдаёт [ [ts, o,h,l,c,v], ... ]
            # оборачиваем кэшем по ключу
            key = ("ohlcv", symbol, timeframe, int(limit))
            val = self._cache.get(key)
            if val is not None:
                return val
            data = await exch.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
            self._cache.put(key, data)
            return data  # type: ignore[return-value]
        # Фоллбек — если у PaperBroker есть прокси-методы
        if hasattr(self._broker, "fetch_ohlcv"):
            key = ("ohlcv", symbol, timeframe, int(limit))
            val = self._cache.get(key)
            if val is not None:
                return val
            data = await self._broker.fetch_ohlcv(symbol, timeframe=timeframe, limit=int(limit))
            self._cache.put(key, data)
            return data
        return []

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        # Используем уже существующий метод брокера
        if hasattr(self._broker, "fetch_ticker"):
            key = ("ticker", symbol)
            val = self._cache.get(key)
            if val is not None:
                return val  # type: ignore[return-value]
            t = await self._broker.fetch_ticker(symbol)
            self._cache.put(key, t)
            return t  # type: ignore[return-value]
        return {}
