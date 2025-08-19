# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import binascii
import logging
import re
import time
from typing import Any, Dict, List, Optional

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger("brokers.ccxt_exchange")

SAFE_TEXT_RE = re.compile(r"[0-9A-Za-z_.-]+")


def _safe_gate_text(idem_key: Optional[str]) -> str:
    ts = int(time.time() * 1000)
    body = f"cai{format(ts % 10**9, 'x')}"
    if idem_key:
        h = format(binascii.crc32(idem_key.encode("utf-8")) & 0xFFFF_FFFF, "x")
        body = f"{body}{h}"
    body = body[:28]
    if not SAFE_TEXT_RE.fullmatch(body):
        body = re.sub(r"[^0-9A-Za-z_.-]", ".", body)
        body = body[:28]
    return f"t-{body}"


def _kind_from_exc(e: Exception) -> str:
    name = e.__class__.__name__.lower()
    if "rate" in name:
        return "rate_limit"
    if "ddos" in name:
        return "ddos"
    if "timeout" in name:
        return "timeout"
    if "network" in name:
        return "network"
    if "auth" in name or "permission" in name:
        return "auth"
    if "insufficient" in name:
        return "funds"
    if "invalidorder" in name:
        return "invalid_order"
    return "unknown"


class CCXTExchange:
    """
    Тонкая обёртка над ccxt со встроенным circuit-breaker,
    мягким rate-limit-хуком и нормализацией параметров под Gate.
    """

    def __init__(self, *, settings: Any):
        self.settings = settings
        # Инициализируем CCXT
        try:
            import ccxt  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("ccxt is required") from e

        exchange_id = getattr(settings, "EXCHANGE", "gateio").lower()
        api_key = getattr(settings, "API_KEY", None)
        api_secret = getattr(settings, "API_SECRET", None)

        if not hasattr(ccxt, exchange_id):  # pragma: no cover
            raise RuntimeError(f"Unsupported exchange: {exchange_id}")

        klass = getattr(ccxt, exchange_id)
        self.ccxt = klass({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "createMarketBuyOrderRequiresPrice": False,
            },
        })

        # Circuit Breaker
        self.cb = CircuitBreaker(
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 15.0)),
            half_open_successes=int(getattr(settings, "CB_HALF_OPEN_SUCCESSES", 2)),
        )

        # Внутренний лимитер (если передан контейнером)
        self.limiter = getattr(settings, "limiter", None)

        # Загрузим метаданные рынков (precision/limits)
        try:
            self.ccxt.load_markets()
        except Exception as e:
            logger.warning("ccxt.load_markets failed: %s", e)

    # ---------- общий помощник ----------

    def _rl(self, bucket: str) -> None:
        lim = self.limiter
        if lim is not None and hasattr(lim, "try_acquire"):
            if not lim.try_acquire(bucket):
                # имитируем RateLimitExceeded — пусть наверху решают (ретраи/CB)
                from ccxt.base.errors import RateLimitExceeded  # type: ignore
                raise RateLimitExceeded(f"local limiter bucket={bucket} exhausted")

    # ---------- рыночные данные ----------

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        from ccxt.base.errors import RateLimitExceeded, NetworkError, ExchangeNotAvailable, RequestTimeout  # type: ignore
        try:
            self._rl("market_data")
            res = self.ccxt.fetch_ticker(symbol)
            self.cb.record_success()
            return res or {}
        except (RateLimitExceeded, NetworkError, ExchangeNotAvailable, RequestTimeout) as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    # ---------- торговля ----------

    def create_order(
        self,
        *,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        from ccxt.base.errors import RateLimitExceeded, NetworkError, ExchangeNotAvailable, RequestTimeout  # type: ignore
        p = dict(params or {})
        # Gate.io client order id
        if str(getattr(self.settings, "EXCHANGE", "gateio")).lower() == "gateio":
            p.setdefault("text", _safe_gate_text(idempotency_key))
            p.setdefault("createMarketBuyOrderRequiresPrice", False)

        try:
            self._rl("orders")
            res = self.ccxt.create_order(symbol, type, side, amount, price, p)
            self.cb.record_success()
            return res or {}
        except (RateLimitExceeded, NetworkError, ExchangeNotAvailable, RequestTimeout) as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            self._rl("orders")
            res = self.ccxt.cancel_order(id, symbol, params or {})
            self.cb.record_success()
            return res or {}
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            self._rl("orders")
            res = self.ccxt.fetch_order(id, symbol, params or {})
            self.cb.record_success()
            return res or {}
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            self._rl("orders")
            res = self.ccxt.fetch_open_orders(symbol, since, limit, params or {})
            self.cb.record_success()
            return res or []
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise
