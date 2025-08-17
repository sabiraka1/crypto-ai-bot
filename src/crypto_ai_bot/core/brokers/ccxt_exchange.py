# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.core.brokers.base import ExchangeInterface, TransientExchangeError, PermanentExchangeError
from crypto_ai_bot.utils.metrics import inc, observe, set_gauge
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

def _import_ccxt():
    try:
        import ccxt  # type: ignore
        return ccxt
    except Exception as e:
        raise PermanentExchangeError(f"ccxt not installed: {e}")

class CcxtExchange(ExchangeInterface):
    def __init__(self, instance, circuit: CircuitBreaker, exchange_name: str = "binance"):
        self._ccxt = instance
        self._cb = circuit
        self._name = exchange_name

    @classmethod
    def from_settings(cls, cfg) -> "CcxtExchange":
        ccxt = _import_ccxt()
        exchange_name = getattr(cfg, "EXCHANGE", "binance")
        kwargs = {
            "apiKey": getattr(cfg, "API_KEY", None),
            "secret": getattr(cfg, "API_SECRET", None),
            "enableRateLimit": True,
            "options": {"adjustForTimeDifference": True},
        }
        instance = getattr(ccxt, exchange_name) (kwargs)
        circuit = CircuitBreaker()
        return cls(instance, circuit, exchange_name)

    # ---- helpers ----
    def _cb_call(self, method_name: str, fn, *args, **kwargs):
        """
        Обёртка через circuit-breaker + метрики.
        """
        inc("broker_requests_total", {"exchange": self._name, "method": method_name})
        try:
            def _inner():
                return fn(*args, **kwargs)

            res = self._cb.call(
                _inner,
                key=f"{self._name}:{method_name}",
                timeout=10.0,
                fail_threshold=5,
                open_seconds=30.0,
            )
            return res
        except Exception as e:
            # классифицируем
            inc("broker_errors_total", {"exchange": self._name, "method": method_name, "type": type(e).__name__})
            if isinstance(e, PermanentExchangeError):
                raise
            # простая эвристика: сетевые/429/5xx считаем transient
            raise TransientExchangeError(str(e))

    # ---- interface ----
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        ccxt = _import_ccxt()
        m = "fetch_ohlcv"
        return self._cb_call(m, self._ccxt.fetch_ohlcv, symbol, timeframe, limit)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        m = "fetch_ticker"
        return self._cb_call(m, self._ccxt.fetch_ticker, symbol)

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> Dict[str, Any]:
        m = "create_order"
        # ccxt принимает float; аккуратно приводим
        _amount = float(amount)
        _price = float(price) if price is not None else None
        return self._cb_call(m, self._ccxt.create_order, symbol, type_, side, _amount, _price)

    def fetch_balance(self) -> Dict[str, Any]:
        m = "fetch_balance"
        return self._cb_call(m, self._ccxt.fetch_balance)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        m = "cancel_order"
        return self._cb_call(m, self._ccxt.cancel_order, order_id)
