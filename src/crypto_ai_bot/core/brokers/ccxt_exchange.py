# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import time
import zlib
import random
import asyncio
from typing import Any, Dict, Optional

import ccxt  # синхронный; оборачиваем в to_thread
from crypto_ai_bot.utils.rate_limit import GateIOLimiter
from crypto_ai_bot.utils.metrics import inc, observe_histogram
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.retry import retry_async
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = get_logger(__name__)


def _crc32(s: str) -> str:
    return format(zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF, "08x")


def _gateio_text_from(ikey: str) -> str:
    """
    Gate.io clientOrderId -> поле `text`, должно начинаться с 't-' и быть <= 28 байт.
    Инкапсулируем в одном месте.
    """
    base = f"t-{_crc32(ikey)}-{int(time.time())}"
    return base[:28]


class CCXTExchange:
    def __init__(self, *, settings, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.settings = settings
        self.loop = loop or asyncio.get_event_loop()
        self.exchange_id = getattr(settings, "EXCHANGE", "gateio")

        # CCXT client (sync)
        exchange_cls = getattr(ccxt, self.exchange_id)
        self.ccxt = exchange_cls(
            {
                "apiKey": getattr(settings, "API_KEY", None),
                "secret": getattr(settings, "API_SECRET", None),
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                    # важно для market buy без price
                    "createMarketBuyOrderRequiresPrice": False,
                },
            }
        )

        # Circuit Breaker
        self.cb = CircuitBreaker(
            name="ccxt_broker",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )

        # Per-endpoint limiter
        self.limiter = GateIOLimiter(settings)

    # --------- helpers ---------
    def _rl(self, bucket: str) -> bool:
        try:
            return self.limiter.try_acquire(bucket)
        except Exception:
            # лимитер никогда не должен валить поток; fallback допускаем
            return True

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _with_retries(self, bucket: str, fn, *args, **kwargs):
        if not self.cb.allow():
            inc("broker_circuit_open_total", {"exchange": self.exchange_id})
            raise RuntimeError("circuit_open")

        # простая защита от «заливки» при полном исчерпании бакета
        for _ in range(5):
            if self._rl(bucket):
                break
            await asyncio.sleep(0.05 + random.random() * 0.05)

        async def _call():
            try:
                return await self._to_thread(fn, *args, **kwargs)
            except ccxt.NetworkError as e:
                self.cb.record_error("network", e)
                raise
            except ccxt.RateLimitExceeded as e:
                self.cb.record_error("rate_limit", e)
                raise
            except ccxt.DDoSProtection as e:
                self.cb.record_error("ddos", e)
                raise
            except ccxt.ExchangeNotAvailable as e:
                self.cb.record_error("unavailable", e)
                raise

        @retry_async(
            attempts=int(getattr(self.settings, "BROKER_RETRY_ATTEMPTS", 4)),
            backoff_base=float(getattr(self.settings, "BROKER_RETRY_BASE_SEC", 0.2)),
            backoff_factor=float(getattr(self.settings, "BROKER_RETRY_FACTOR", 2.0)),
            jitter=True,
            retry_exceptions=(ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.DDoSProtection, ccxt.ExchangeNotAvailable),
        )
        async def _retryable():
            return await _call()

        res = await _retryable()
        self.cb.record_success()
        return res

    # --------- public API ----------
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        res = await self._with_retries("market_data", self.ccxt.fetch_ticker, symbol)
        observe_histogram("broker_fetch_ticker_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id})
        return res

    async def fetch_balance(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        res = await self._with_retries("account", self.ccxt.fetch_balance)
        observe_histogram("broker_fetch_balance_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id})
        return res

    async def fetch_open_orders(self, symbol: Optional[str] = None):
        bucket = "orders"
        t0 = time.perf_counter()
        if symbol:
            res = await self._with_retries(bucket, self.ccxt.fetch_open_orders, symbol)
        else:
            res = await self._with_retries(bucket, self.ccxt.fetch_open_orders)
        observe_histogram("broker_fetch_open_orders_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id})
        return res

    async def fetch_order(self, order_id: str, symbol: Optional[str] = None):
        t0 = time.perf_counter()
        if symbol:
            res = await self._with_retries("orders", self.ccxt.fetch_order, order_id, symbol)
        else:
            res = await self._with_retries("orders", self.ccxt.fetch_order, order_id)
        observe_histogram("broker_fetch_order_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id})
        return res

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: float, idempotency_key: str):
        """
        Gate.io: рыночная покупка указывается в КОТИРУЕМОЙ валюте (USDT).
        """
        client_text = _gateio_text_from(idempotency_key)
        params = {"text": client_text}
        t0 = time.perf_counter()
        res = await self._with_retries(
            "orders",
            self.ccxt.create_order,
            symbol,
            "market",
            "buy",
            quote_amount,  # для Gate/ccxt это notional в QUOTE
            None,
            params,
        )
        observe_histogram("broker_create_order_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id, "side": "buy"})
        return res

    async def create_market_sell_base(self, *, symbol: str, base_amount: float, idempotency_key: str):
        client_text = _gateio_text_from(idempotency_key)
        params = {"text": client_text}
        t0 = time.perf_counter()
        res = await self._with_retries(
            "orders",
            self.ccxt.create_order,
            symbol,
            "market",
            "sell",
            base_amount,  # для sell указываем количество BASE
            None,
            params,
        )
        observe_histogram("broker_create_order_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id, "side": "sell"})
        return res

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None):
        t0 = time.perf_counter()
        if symbol:
            res = await self._with_retries("orders", self.ccxt.cancel_order, order_id, symbol)
        else:
            res = await self._with_retries("orders", self.ccxt.cancel_order, order_id)
        observe_histogram("broker_cancel_order_latency_sec", time.perf_counter() - t0, {"exchange": self.exchange_id})
        return res
