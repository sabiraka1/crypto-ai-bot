"""
CCXT market data adapter with caching.

Provides market data from CCXT exchanges with TTL caching
to reduce API calls and improve performance.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Union

from crypto_ai_bot.core.application.ports import BrokerPort, TickerDTO
from crypto_ai_bot.core.domain.signals.feature_pipeline import Candle
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)

# Type aliases for CCXT data structures
_OHLCV = list[list[Any]]  # [[timestamp(ms), open, high, low, close, volume], ...]
_TICKER = dict[str, Any]  # {'bid': ..., 'ask': ..., 'last': ..., ...}


# ---------------- TTL cache ----------------

class TTLCache:
    """Simple TTL cache for market data."""

    def __init__(self, ttl_sec: float = 30.0, max_size: int = 1000):
        """
        Args:
            ttl_sec: Time to live in seconds
            max_size: Max number of entries to keep
        """
        self.ttl_sec = float(ttl_sec)
        self.max_size = int(max_size)
        self._cache: dict[Any, tuple[Any, float]] = {}

    def get(self, key: Any) -> Optional[Any]:
        """Get value from cache if not expired."""
        row = self._cache.get(key)
        if not row:
            return None
        value, ts = row
        age = datetime.now(timezone.utc).timestamp() - ts
        if age < self.ttl_sec:
            return value
        # expired
        self._cache.pop(key, None)
        return None

    def put(self, key: Any, value: Any) -> None:
        """Put value in cache with current timestamp."""
        # basic LRU-ish cap: drop oldest one if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.items(), key=lambda kv: kv[1][1])[0]
            self._cache.pop(oldest_key, None)
        self._cache[key] = (value, datetime.now(timezone.utc).timestamp())

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def size(self) -> int:
        """Get number of cached entries."""
        return len(self._cache)


# --------------- utils ---------------

async def _maybe_await(fn_or_coro: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Call a function/coroutine in a sync/async tolerant way.
    """
    try:
        if inspect.iscoroutine(fn_or_coro):
            return await fn_or_coro
        if callable(fn_or_coro):
            res = fn_or_coro(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        # not callable — maybe already result
        return fn_or_coro
    except Exception:
        raise


def _to_dt_iso(value: Any) -> datetime:
    """Parse datetime from iso string or epoch ms; default to now(UTC)."""
    try:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            # assume ms if large
            ts = float(value) / 1000.0 if float(value) > 1e10 else float(value)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(value, str):
            s = value.replace("Z", "+00:00")
            return datetime.fromisoformat(s)
    except Exception:
        pass
    return datetime.now(timezone.utc)


# --------------- main provider ---------------

class CCXTMarketData:
    """
    Market data provider using CCXT.

    Fetches OHLCV and ticker data from exchanges via CCXT
    with TTL caching to optimize API usage.
    """

    def __init__(
        self,
        broker: BrokerPort,
        cache_ttl_sec: float = 30.0,
        max_cache_size: int = 1000,
    ):
        """
        Initialize market data provider.

        Args:
            broker: Broker instance (must have CCXT exchange)
            cache_ttl_sec: Cache time to live in seconds
            max_cache_size: Maximum cache entries
        """
        self._broker = broker
        self._cache = TTLCache(ttl_sec=cache_ttl_sec, max_size=max_cache_size)

        # Extract CCXT exchange from broker (sync or async supported)
        self._exchange = self._get_exchange(broker)

        _log.info(
            "ccxt_market_data_initialized",
            extra={
                "cache_ttl": cache_ttl_sec,
                "max_cache_size": max_cache_size,
                "has_exchange": self._exchange is not None,
            },
        )

    # -------- exchange access --------

    def _get_exchange(self, broker: Any) -> Optional[Any]:
        """Extract CCXT exchange instance from broker."""
        for attr in ("exchange", "_exchange", "ccxt_exchange"):
            if hasattr(broker, attr):
                return getattr(broker, attr)
        # If broker itself looks like a CCXT exchange
        if hasattr(broker, "fetch_ohlcv") and hasattr(broker, "fetch_ticker"):
            return broker
        return None

    # -------- OHLCV --------

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 100,
    ) -> list[Candle]:
        """
        Get OHLCV candles.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d, 1w)
            limit: Number of candles to fetch

        Returns:
            List of Candle objects
        """
        cache_key = ("ohlcv", symbol, timeframe, int(limit))
        cached = self._cache.get(cache_key)
        if cached is not None:
            _log.debug("ohlcv_cache_hit", extra={"symbol": symbol, "timeframe": timeframe, "limit": limit})
            return cached  # type: ignore[return-value]

        try:
            raw = await self._fetch_ohlcv_raw(symbol, timeframe, limit)
            candles = self._parse_ohlcv(raw)
            self._cache.put(cache_key, candles)
            _log.debug("ohlcv_fetched", extra={"symbol": symbol, "timeframe": timeframe, "count": len(candles)})
            return candles
        except Exception as e:
            _log.error("ohlcv_fetch_failed", extra={"symbol": symbol, "timeframe": timeframe, "error": str(e)}, exc_info=True)
            return []

    async def _fetch_ohlcv_raw(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> _OHLCV:
        """Fetch raw OHLCV data from exchange or broker."""
        # Prefer exchange if present
        if self._exchange and hasattr(self._exchange, "fetch_ohlcv"):
            return await _maybe_await(self._exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit)  # type: ignore[misc]

        # Fallback: through broker
        if hasattr(self._broker, "fetch_ohlcv"):
            data = await _maybe_await(self._broker.fetch_ohlcv, symbol, timeframe, limit)
            # Support both CCXT-style rows and Candle objects
            out: _OHLCV = []
            for x in data or []:
                if isinstance(x, Candle):
                    out.append([
                        int(x.t_ms), float(x.open), float(x.high), float(x.low), float(x.close), float(x.volume)
                    ])
                elif isinstance(x, (list, tuple)) and len(x) >= 6:
                    # assume [dt|ms, o, h, l, c, v]
                    ts = x[0]
                    if isinstance(ts, datetime):
                        ms = int((ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp() * 1000)
                    elif isinstance(ts, (int, float)):
                        ms = int(ts if ts > 1e10 else ts * 1000)
                    else:
                        ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                    out.append([ms, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])])
            return out

        return []

    def _parse_ohlcv(self, raw_data: _OHLCV) -> list[Candle]:
        """Parse raw CCXT OHLCV data to Candle objects."""
        candles: list[Candle] = []
        for row in raw_data:
            if not row or len(row) < 6:
                continue
            try:
                ts_ms = int(row[0])
                ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                candles.append(
                    Candle(
                        timestamp=ts,
                        open=dec(str(row[1])),
                        high=dec(str(row[2])),
                        low=dec(str(row[3])),
                        close=dec(str(row[4])),
                        volume=dec(str(row[5])),
                    )
                )
            except Exception:
                # skip malformed rows
                continue
        return candles

    # -------- ticker --------

    async def get_ticker(self, symbol: str) -> Optional[TickerDTO]:
        """
        Get current ticker data.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")

        Returns:
            TickerDTO or None if failed
        """
        cache_key = ("ticker", symbol)
        cached = self._cache.get(cache_key)
        if cached is not None:
            _log.debug("ticker_cache_hit", extra={"symbol": symbol})
            return cached  # type: ignore[return-value]

        try:
            raw_ticker = await self._fetch_ticker_raw(symbol)
            if not raw_ticker:
                return None

            ticker = self._parse_ticker(symbol, raw_ticker)
            if ticker:
                self._cache.put(cache_key, ticker)

            _log.debug("ticker_fetched", extra={"symbol": symbol, "last": str(ticker.last) if ticker else None})
            return ticker
        except Exception as e:
            _log.error("ticker_fetch_failed", extra={"symbol": symbol, "error": str(e)}, exc_info=True)
            return None

    async def _fetch_ticker_raw(self, symbol: str) -> _TICKER:
        """Fetch raw ticker data from exchange or broker."""
        if self._exchange and hasattr(self._exchange, "fetch_ticker"):
            return await _maybe_await(self._exchange.fetch_ticker, symbol)  # type: ignore[misc]

        if hasattr(self._broker, "fetch_ticker"):
            # Through broker (expected TickerDTO)
            ticker_dto = await _maybe_await(self._broker.fetch_ticker, symbol)
            if not ticker_dto:
                return {}
            return {
                "bid": float(getattr(ticker_dto, "bid", 0)),
                "ask": float(getattr(ticker_dto, "ask", 0)),
                "last": float(getattr(ticker_dto, "last", 0)),
                "baseVolume": float(getattr(ticker_dto, "volume_24h", 0)),
                "datetime": getattr(ticker_dto, "timestamp", datetime.now(timezone.utc)).isoformat(),
            }

        return {}

    def _parse_ticker(self, symbol: str, raw_ticker: _TICKER) -> Optional[TickerDTO]:
        """Parse raw CCXT ticker to TickerDTO."""
        try:
            bid = dec(str(raw_ticker.get("bid", 0)))
            ask = dec(str(raw_ticker.get("ask", 0)))
            last = dec(str(raw_ticker.get("last", 0)))

            # volume fallbacks
            vol = raw_ticker.get("baseVolume")
            if vol is None:
                vol = raw_ticker.get("quoteVolume", 0)

            volume = dec(str(vol or 0))

            # timestamp: prefer iso, else ms
            if "datetime" in raw_ticker and raw_ticker["datetime"]:
                timestamp = _to_dt_iso(raw_ticker["datetime"])
            elif "timestamp" in raw_ticker and raw_ticker["timestamp"] is not None:
                timestamp = _to_dt_iso(raw_ticker["timestamp"])
            else:
                timestamp = datetime.now(timezone.utc)

            # spread (%), Decimal-safe
            if bid > 0 and ask > 0:
                mid = (bid + ask) / dec("2")
                spread_pct = ((ask - bid) / mid) * dec("100")
            else:
                spread_pct = dec("0")

            return TickerDTO(
                symbol=symbol,
                last=last,
                bid=bid,
                ask=ask,
                spread_pct=spread_pct,
                volume_24h=volume,
                timestamp=timestamp,
            )

        except Exception as e:
            _log.error("ticker_parse_failed", extra={"symbol": symbol, "error": str(e)}, exc_info=True)
            return None

    # -------- orderbook --------

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        """
        Get order book data.

        Args:
            symbol: Trading pair
            limit: Depth of order book

        Returns:
            Order book dict with 'bids' and 'asks'
        """
        cache_key = ("orderbook", symbol, int(limit))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            if self._exchange and hasattr(self._exchange, "fetch_order_book"):
                orderbook = await _maybe_await(self._exchange.fetch_order_book, symbol, limit)
                self._cache.put(cache_key, orderbook)
                return orderbook
        except Exception as e:
            _log.error("orderbook_fetch_failed", extra={"symbol": symbol, "error": str(e)}, exc_info=True)

        return {"bids": [], "asks": []}

    # -------- cache utils --------

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        _log.info("market_data_cache_cleared")


# Export
__all__ = ["CCXTMarketData", "TTLCache"]
