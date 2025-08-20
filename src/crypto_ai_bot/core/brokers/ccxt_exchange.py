# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import asyncio
import binascii
from decimal import Decimal
from typing import Any, Dict, Optional

import ccxt  # type: ignore

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.rate_limit import build_gateio_limiter_from_settings, MultiLimiter
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = get_logger(__name__)


class CCXTExchange:
    """Тонкая обёртка над CCXT с лимитами, CB и clientOrderId для Gate.io."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ccxt = self._build_ccxt(settings)
        self.limiter: MultiLimiter = build_gateio_limiter_from_settings(settings)

        # Circuit Breaker с обязательным name
        self.cb = CircuitBreaker(
            name="ccxt_broker",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )

    # ---------- CCXT init ----------
    def _build_ccxt(self, settings: Settings):
        exchange_id = getattr(settings, "EXCHANGE", "gateio")
        api_key = getattr(settings, "API_KEY", "")
        api_secret = getattr(settings, "API_SECRET", "")

        klass = getattr(ccxt, exchange_id)
        inst = klass({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                # market buy без price
                "createMarketBuyOrderRequiresPrice": False,
            },
        })
        return inst

    # ---------- Helpers ----------
    def _gateio_text_from(self, idem_key: str) -> Optional[str]:
        """Стабильный clientOrderId для Gate.io в параметре `text` (28 байт, [A-Za-z0-9._-], префикс 't-')."""
        try:
            crc = binascii.crc32(idem_key.encode("utf-8")) & 0xFFFFFFFF
            # t- + 8 hex + epoch-ms tail (до лимита длины)
            tail = hex(crc)[2:]
            base = f"t-{tail}"
            # безопасность длины
            return base[:28]
        except Exception:
            return None

    async def _rl(self, bucket: str) -> None:
        # блокирующая попытка на очень короткое окно; если не вышло — лёгкий backoff
        if not self.limiter.try_acquire(bucket):
            await asyncio.sleep(0.05)

    async def _with_retries(self, bucket: str, fn, *a, **kw):
        # circuit breaker
        if not self.cb.allow():
            raise CircuitOpenError("circuit is open")

        attempt = 0
        last_exc = None
        while attempt < int(getattr(self.settings, "HTTP_MAX_ATTEMPTS", 4)):
            attempt += 1
            try:
                await self._rl(bucket)
                return await asyncio.get_event_loop().run_in_executor(None, fn, *a, **kw)
            except ccxt.RateLimitExceeded as e:
                last_exc = e
                self.cb.record_error("rate_limit", e)
                await asyncio.sleep(min(1.0 * attempt, 3.0))
            except (ccxt.NetworkError, ccxt.ExchangeError) as e:
                last_exc = e
                self.cb.record_error("network", e)
                await asyncio.sleep(min(0.5 * attempt, 2.0))
            except Exception as e:
                # логические ошибки — не ретраим
                self.cb.record_error("fatal", e)
                raise
        # истощили попытки
        raise last_exc or RuntimeError("max attempts exceeded")

    # ---------- Public API ----------
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return await self._with_retries("market_data", self.ccxt.fetch_ticker, symbol)

    async def fetch_balance(self) -> Dict[str, Any]:
        return await self._with_retries("account", self.ccxt.fetch_balance)

    async def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            return await self._with_retries("orders", self.ccxt.fetch_order, order_id, symbol)
        return await self._with_retries("orders", self.ccxt.fetch_order, order_id)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> Any:
        if symbol:
            return await self._with_retries("orders", self.ccxt.fetch_open_orders, symbol)
        return await self._with_retries("orders", self.ccxt.fetch_open_orders)

    async def create_order(
        self,
        *,
        symbol: str,
        type: str,
        side: str,
        amount: Optional[float] = None,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Маркет/лимит — CID генерируем тут (единая точка), place_order никаких CID не делает."""
        p = dict(params or {})
        if getattr(self.settings, "EXCHANGE", "gateio") == "gateio":
            txt = self._gateio_text_from(idempotency_key or f"{symbol}:{side}:{now_ms()}")
            if txt:
                p["text"] = txt

        fn = self.ccxt.create_order
        return await self._with_retries("orders", fn, symbol, type, side, amount, price, p)
