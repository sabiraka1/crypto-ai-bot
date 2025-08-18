from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Dict, Optional

import ccxt  # синхронная версия под server.py

from .base import ExchangeInterface
from ..events.bus import get_event_bus
from ...utils.metrics import metrics

try:
    from ...utils.circuit_breaker import CircuitBreaker
except Exception:
    class CircuitBreaker:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

class _TokenBucket:
    def __init__(self, calls: int, per_seconds: float):
        self.calls = max(1, int(calls))
        self.per = float(per_seconds)
        self._ts = deque()
        self._lock = Lock()
    def acquire(self):
        with self._lock:
            now = time.monotonic()
            while self._ts and (now - self._ts[0]) >= self.per:
                self._ts.popleft()
            if len(self._ts) >= self.calls:
                sleep_for = self.per - (now - self._ts[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                    now = time.monotonic()
                    while self._ts and (now - self._ts[0]) >= self.per:
                        self._ts.popleft()
            self._ts.append(time.monotonic())

class CCXTExchange(ExchangeInterface):
    def __init__(self, settings, bus=None, exchange_name: str = None):
        self.settings = settings
        self.exchange_name = (exchange_name or getattr(settings, "EXCHANGE", "gateio")).lower()
        self.bus = bus or get_event_bus()
        self.breaker = CircuitBreaker(f"ccxt.{self.exchange_name}.http")

        timeout_ms = int(getattr(settings, "HTTP_TIMEOUT_MS", 15000))
        klass = getattr(ccxt, self.exchange_name)
        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
            "timeout": timeout_ms,
        })

        calls = int(getattr(settings, "CCXT_LOCAL_RL_CALLS", 8))
        window = float(getattr(settings, "CCXT_LOCAL_RL_WINDOW", 1.0))
        self._bucket = _TokenBucket(calls=calls, per_seconds=window)

        self.m_lat = {
            "fetch_ticker": metrics.histogram("ccxt_fetch_ticker_seconds", "Latency of fetch_ticker", ["ex"]),
            "fetch_ohlcv":  metrics.histogram("ccxt_fetch_ohlcv_seconds", "Latency of fetch_ohlcv", ["ex"]),
            "create_order": metrics.histogram("ccxt_create_order_seconds", "Latency of create_order", ["ex"]),
            "cancel_order": metrics.histogram("ccxt_cancel_order_seconds", "Latency of cancel_order", ["ex"]),
        }
        self.m_err = metrics.counter("ccxt_errors_total", "Total CCXT errors", ["ex", "op"])

    def _with_rl(self):
        self._bucket.acquire()
    def _obs(self, op: str, t0: float):
        self.m_lat[op].labels(self.exchange_name).observe(time.perf_counter() - t0)
    def _dlq(self, op: str, err: Exception, extra: Optional[Dict[str, Any]] = None):
        try:
            payload = {"op": op, "exchange": self.exchange_name, "error": f"{type(err).__name__}: {err}"}
            if extra: payload.update(extra)
            if self.bus and hasattr(self.bus, "publish"):
                self.bus.publish({"type": "dlq.error", "payload": payload})
        except Exception:
            pass

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        self._with_rl()
        t0 = time.perf_counter()
        try:
            with self.breaker:
                return self.ccxt.fetch_ticker(symbol)
        except Exception as e:
            self.m_err.labels(self.exchange_name, "fetch_ticker").inc()
            self._dlq("fetch_ticker", e, {"symbol": symbol})
            raise
        finally:
            self._obs("fetch_ticker", t0)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        self._with_rl()
        t0 = time.perf_counter()
        try:
            with self.breaker:
                return self.ccxt.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            self.m_err.labels(self.exchange_name, "fetch_ohlcv").inc()
            self._dlq("fetch_ohlcv", e, {"symbol": symbol, "timeframe": timeframe, "limit": limit})
            raise
        finally:
            self._obs("fetch_ohlcv", t0)

    def create_order(self, symbol: str, side: str, type_: str, amount: float,
                     price: Optional[float] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._with_rl()
        t0 = time.perf_counter()
        p = dict(params or {})
        client_oid = p.pop("clientOrderId", None) or p.pop("client_oid", None) or p.pop("text", None)
        if client_oid:
            p.setdefault("clientOrderId", client_oid)
            p.setdefault("text", str(client_oid)[:32])
        try:
            with self.breaker:
                if type_ == "market":
                    return self.ccxt.create_order(symbol, type="market", side=side, amount=amount, price=None, params=p)
                return self.ccxt.create_order(symbol, type="limit", side=side, amount=amount, price=price, params=p)
        except Exception as e:
            self.m_err.labels(self.exchange_name, "create_order").inc()
            self._dlq("create_order", e, {"symbol": symbol, "side": side, "type": type_, "amount": amount})
            raise
        finally:
            self._obs("create_order", t0)

    def cancel_order(self, id_: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._with_rl()
        t0 = time.perf_counter()
        try:
            with self.breaker:
                return self.ccxt.cancel_order(id_, symbol, params or {})
        except Exception as e:
            self.m_err.labels(self.exchange_name, "cancel_order").inc()
            self._dlq("cancel_order", e, {"orderId": id_, "symbol": symbol})
            raise
        finally:
            self._obs("cancel_order", t0)

    def fetch_balance(self) -> Dict[str, Any]:
        self._with_rl()
        try:
            with self.breaker:
                return self.ccxt.fetch_balance()
        except Exception as e:
            self.m_err.labels(self.exchange_name, "fetch_balance").inc()
            self._dlq("fetch_balance", e, {})
            raise
