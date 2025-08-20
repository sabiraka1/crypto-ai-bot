# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import ccxt  # sync client
from crypto_ai_bot.utils.rate_limit import GateIOLimiter, MultiLimiter
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker  # существующий у вас

logger = logging.getLogger(__name__)

class CCXTExchange:
    """
    Async wrapper over sync ccxt.* client:
      - per-endpoint rate limiting (orders/market_data/account)
      - circuit breaker with backoff
      - TTL cache for fetch_ticker
      - Gate.io clientOrderId via params['text'] (generated HERE only)
    """

    def __init__(self, settings, ccxt_client: Optional[Any] = None):
        self.settings = settings
        exchange_id = getattr(settings, "EXCHANGE", "gateio").lower()
        self.ccxt = ccxt_client or getattr(ccxt, exchange_id)({
            "apiKey": settings.API_KEY,
            "secret": settings.API_SECRET,
            "enableRateLimit": True,
            "options": {
                "createMarketBuyOrderRequiresPrice": False,
            },
        })

        # Per-endpoint limiter
        self.limiter = GateIOLimiter(
            orders_capacity=getattr(settings, "RL_ORDERS_CAP", 100),
            orders_window_sec=getattr(settings, "RL_ORDERS_WIN", 10.0),
            market_capacity=getattr(settings, "RL_MKT_CAP", 600),
            market_window_sec=getattr(settings, "RL_MKT_WIN", 10.0),
            account_capacity=getattr(settings, "RL_ACC_CAP", 300),
            account_window_sec=getattr(settings, "RL_ACC_WIN", 10.0),
        )
        self.global_limiter = MultiLimiter(global_rps=getattr(settings, "GLOBAL_RPS", 10.0))

        # Circuit breaker
        self.cb = CircuitBreaker(
            name="ccxt_broker",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )

        # ticker TTL cache
        self._ticker_ttl_ms = int(getattr(settings, "TICKER_TTL_MS", 2500))
        self._ticker_cache: Dict[str, Tuple[Dict[str, Any], int]] = {}

    async def _call(self, endpoint: str, fn, *args, **kwargs):
        # global + endpoint rate limit
        if not self.global_limiter.try_acquire():
            await asyncio.sleep(0.05)
        if not self.limiter.try_acquire(endpoint):
            await asyncio.sleep(0.05)

        if not self.cb.allow():
            raise RuntimeError("circuit_open")

        try:
            # run blocking ccxt in thread
            return await asyncio.to_thread(fn, *args, **kwargs)
        except ccxt.RateLimitExceeded as e:
            self.cb.record_error("rate_limit", e)
            inc("ccxt_rate_limit_total", {"endpoint": endpoint})
            raise
        except ccxt.NetworkError as e:
            self.cb.record_error("network", e)
            inc("ccxt_network_errors_total", {"endpoint": endpoint})
            raise
        except ccxt.ExchangeError as e:
            self.cb.record_error("exchange", e)
            inc("ccxt_exchange_errors_total", {"endpoint": endpoint})
            raise
        except Exception as e:  # logic/unknown
            self.cb.record_error("unknown", e)
            inc("ccxt_unknown_errors_total", {"endpoint": endpoint})
            raise

    # -------- Market data

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        now = now_ms()
        cached = self._ticker_cache.get(symbol)
        if cached and now < cached[1]:
            return cached[0]
        data = await self._call("market_data", self.ccxt.fetch_ticker, symbol)
        self._ticker_cache[symbol] = (data, now + self._ticker_ttl_ms)
        return data

    async def fetch_balance(self) -> Dict[str, Any]:
        return await self._call("account", self.ccxt.fetch_balance)

    # -------- Orders

    @staticmethod
    def _gateio_text_from(idempotency_key: Optional[str], symbol: str, side: str) -> str:
        """
        Gate.io client id rules: must start with 't-' and <= 28 bytes, allowed [A-Za-z0-9._-]
        We compress the idempotency_key if present, else timestamp fallback.
        """
        base = idempotency_key or f"{symbol}-{side}-{int(time.time())}"
        # simple compaction
        safe = "".join(ch for ch in base if ch.isalnum() or ch in "._-")
        cid = f"t-{safe}"
        return cid[:28]

    async def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        # Ensure Gate clientOrderId/text present ONLY here
        if "text" not in params:
            params["text"] = self._gateio_text_from(params.get("idempotency_key"), symbol, side)

        fn = self.ccxt.create_order
        if type == "market" and side == "buy":
            # For market buy, ccxt expects amount as quote notional when option is set
            # price is ignored by gate with createMarketBuyOrderRequiresPrice=False
            return await self._call("orders", fn, symbol, type, side, amount, None, params)
        return await self._call("orders", fn, symbol, type, side, amount, price, params)

    async def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            return await self._call("orders", self.ccxt.fetch_order, order_id, symbol)
        return await self._call("orders", self.ccxt.fetch_order, order_id)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> Any:
        if symbol:
            return await self._call("orders", self.ccxt.fetch_open_orders, symbol)
        return await self._call("orders", self.ccxt.fetch_open_orders)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            return await self._call("orders", self.ccxt.cancel_order, order_id, symbol)
        return await self._call("orders", self.ccxt.cancel_order, order_id)
