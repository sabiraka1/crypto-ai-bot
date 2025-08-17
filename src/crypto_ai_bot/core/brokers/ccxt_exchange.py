# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol

class CcxtExchange:
    """
    Лёгкий адаптер ccxt к нашему интерфейсу.
    Сделан устойчивым: ретраи/CB и метрики без нарушения try/except потоков.
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.cb = CircuitBreaker()
        self._ccxt = None

    @classmethod
    def from_settings(cls, cfg) -> "CcxtExchange":
        return cls(cfg)

    # lazy import ccxt
    def _client(self):
        if self._ccxt is None:
            import ccxt  # type: ignore
            ex_name = getattr(self.cfg, "EXCHANGE", "binance")
            ex = getattr(ccxt, ex_name)()
            ex.enableRateLimit = True
            self._ccxt = ex
        return self._ccxt

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        ex_sym = to_exchange_symbol(symbol, getattr(self.cfg, "EXCHANGE", "binance"))
        t0 = time.perf_counter()
        try:
            def _fn():
                return self._client().fetch_ticker(ex_sym)
            res = self.cb.call(_fn, key=f"fetch_ticker:{ex_sym}", timeout=5.0, fail_threshold=5, open_seconds=15.0)
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ticker", "code": "200"})
            metrics.observe("broker_latency_ms", latency, {"method": "fetch_ticker"})
            return res
        except Exception as e:
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ticker", "code": "599"})
            metrics.observe("broker_latency_ms", latency, {"method": "fetch_ticker"})
            raise

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        ex_sym = to_exchange_symbol(symbol, getattr(self.cfg, "EXCHANGE", "binance"))
        t0 = time.perf_counter()
        try:
            def _fn():
                return self._client().fetch_ohlcv(ex_sym, timeframe=timeframe, limit=limit)
            res = self.cb.call(_fn, key=f"fetch_ohlcv:{ex_sym}:{timeframe}", timeout=10.0, fail_threshold=5, open_seconds=15.0)
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ohlcv", "code": "200"})
            metrics.observe("broker_latency_ms", latency, {"method": "fetch_ohlcv"})
            return res
        except Exception:
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "fetch_ohlcv", "code": "599"})
            metrics.observe("broker_latency_ms", latency, {"method": "fetch_ohlcv"})
            raise

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None):
        ex_sym = to_exchange_symbol(symbol, getattr(self.cfg, "EXCHANGE", "binance"))
        t0 = time.perf_counter()
        params = {"type": type_, "side": side, "amount": float(amount)}
        if price is not None:
            params["price"] = float(price)
        try:
            def _fn():
                if price is not None:
                    return self._client().create_order(ex_sym, type_, side, float(amount), float(price))
                return self._client().create_order(ex_sym, type_, side, float(amount))
            res = self.cb.call(_fn, key=f"create_order:{ex_sym}", timeout=10.0, fail_threshold=5, open_seconds=15.0)
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "create_order", "code": "200"})
            metrics.observe("broker_latency_ms", latency, {"method": "create_order"})
            return res
        except Exception:
            latency = int((time.perf_counter() - t0) * 1000)
            metrics.inc("broker_requests_total", {"exchange": "ccxt", "method": "create_order", "code": "599"})
            metrics.observe("broker_latency_ms", latency, {"method": "create_order"})
            raise
