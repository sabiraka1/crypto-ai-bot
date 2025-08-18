# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

import time

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover
    ccxt = None  # type: ignore


class CCXTExchange(ExchangeInterface):
    """
    CCXT-адаптер с защитой:
      • все сетевые вызовы через CircuitBreaker
      • мягкие тайм-ауты, метрики, нормализация символа
    """

    def __init__(self, client: Any, *, cfg: Any, breaker: Optional[CircuitBreaker] = None) -> None:
        self._client = client
        self.cfg = cfg
        self._breaker = breaker or CircuitBreaker()
        self._bus = None

    # ------ фабрика, которую вызывает create_broker() ------
    @classmethod
    def from_settings(cls, cfg) -> "CCXTExchange":
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        ex_name = str(getattr(cfg, "EXCHANGE", "binance")).lower()
        if not hasattr(ccxt, ex_name):
            raise RuntimeError(f"unsupported exchange: {ex_name}")

        klass = getattr(ccxt, ex_name)
        opts: Dict[str, Any] = {"enableRateLimit": True, "timeout": 10_000}

        api_key = getattr(cfg, "API_KEY", None)
        api_secret = getattr(cfg, "API_SECRET", None)
        subaccount = getattr(cfg, "SUBACCOUNT", None)

        if api_key and api_secret:
            opts["apiKey"] = api_key
            opts["secret"] = api_secret
            if subaccount:
                # у некоторых бирж это 'headers'/'uid' — оставим мягко:
                opts["headers"] = {"FTX-SUBACCOUNT": subaccount}

        client = klass(opts)
        return cls(client, cfg=cfg, breaker=CircuitBreaker())

    # необязательная шина событий
    def set_bus(self, bus) -> None:
        self._bus = bus

    # ------ helpers ------
    def _call(self, fn, *, key: str, timeout: float = 2.5):
        t0 = time.time()
        try:
            res = self._breaker.call(fn, key=key, timeout=timeout)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": key, "code": "200"})
            return res
        except Exception as e:
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": key, "code": "error"})
            # для некоторых мест полезно пробросить в DLQ
            if self._bus:
                try:
                    self._bus.publish({"type": "BrokerError", "key": key, "error": f"{type(e).__name__}: {e}"})
                except Exception:
                    pass
            raise
        finally:
            metrics.observe_histogram("latency_broker_seconds", max(0.0, time.time() - t0))

    # ------ интерфейс ------
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = to_exchange_symbol(symbol)
        def _fn():
            return self._client.fetch_ticker(sym)
        return self._call(_fn, key="fetch_ticker", timeout=3.0)

    def fetch_order_book(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        sym = to_exchange_symbol(symbol)
        def _fn():
            return self._client.fetch_order_book(sym, limit=limit)
        return self._call(_fn, key="fetch_order_book", timeout=3.0)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        sym = to_exchange_symbol(symbol)
        tf = timeframe
        lim = int(limit)
        def _fn():
            return self._client.fetch_ohlcv(sym, timeframe=tf, limit=lim)
        return self._call(_fn, key="fetch_ohlcv", timeout=5.0)

    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        sym = to_exchange_symbol(symbol)
        amt = float(amount)
        px = float(price) if price is not None else None
        def _fn():
            if type_ == "market":
                return self._client.create_order(sym, "market", side, amt)
            return self._client.create_order(sym, "limit", side, amt, px)
        return self._call(_fn, key="create_order", timeout=5.0)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        def _fn():
            return self._client.cancel_order(order_id)
        return self._call(_fn, key="cancel_order", timeout=3.0)

    def fetch_balance(self) -> Dict[str, Any]:
        def _fn():
            return self._client.fetch_balance()
        return self._call(_fn, key="fetch_balance", timeout=4.0)
