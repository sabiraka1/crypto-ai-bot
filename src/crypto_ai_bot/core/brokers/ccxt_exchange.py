# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from .base import ExchangeInterface, TransientExchangeError, PermanentExchangeError
from .symbols import to_exchange_symbol
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from crypto_ai_bot.utils.rate_limit import rate_limit
from crypto_ai_bot.utils.retry import retry  # предполагается, что у тебя уже есть utils/retry.py


try:
    import ccxt  # type: ignore
except Exception as e:  # pragma: no cover
    ccxt = None
    _import_error = e


@dataclass
class CcxtExchange(ExchangeInterface):
    """
    Адаптер ccxt к ExchangeInterface.
    Поддерживает circuit breaker, rate limits и retry/backoff.
    """
    client: Any
    exchange_name: str
    contract: str  # 'spot' | 'linear' | 'inverse'
    breaker: CircuitBreaker

    # -------------------------- Фабрика --------------------------

    @classmethod
    def from_settings(cls, cfg) -> "CcxtExchange":
        if ccxt is None:
            raise RuntimeError(f"ccxt import failed: {_import_error!r}")

        name = getattr(cfg, "EXCHANGE", "bybit").lower()
        contract = getattr(cfg, "CONTRACT_TYPE", "spot").lower()

        # Инициализация клиента ccxt
        if not hasattr(ccxt, name):
            raise RuntimeError(f"Unsupported exchange for ccxt: {name}")

        klass = getattr(ccxt, name)
        client = klass({
            "apiKey": getattr(cfg, "API_KEY", None),
            "secret": getattr(cfg, "API_SECRET", None),
            "enableRateLimit": True,
            "timeout": int(getattr(cfg, "BROKER_TIMEOUT_MS", 15_000)),
            # proxy/headers здесь, если нужно
        })

        breaker = CircuitBreaker(
            fail_threshold=int(getattr(cfg, "BROKER_BREAKER_FAILS", 5)),
            open_seconds=float(getattr(cfg, "BROKER_BREAKER_OPEN_SECONDS", 30)),
            half_open_max_calls=int(getattr(cfg, "BROKER_HALF_OPEN_CALLS", 1)),
        )

        return cls(client=client, exchange_name=name, contract=contract, breaker=breaker)

    # -------------------------- Нормализатор --------------------------

    def _ex_symbol(self, symbol: str) -> str:
        return to_exchange_symbol(self.exchange_name, symbol, contract=self.contract)  # канон → биржа

    # -------------------------- Обёртки вызовов --------------------------

    def _wrap_call(self, key: str, fn, *args, **kwargs):
        """
        Единая точка: circuit breaker + retry/backoff + метрики.
        """
        timeout = float(kwargs.pop("_timeout", getattr(self.client, "timeout", 15_000)) or 15_000) / 1000.0

        @retry(
            retries=int(kwargs.pop("_retries", 3)),
            backoff=float(kwargs.pop("_backoff", 0.5)),
            jitter=float(kwargs.pop("_jitter", 0.2)),
            on=(Exception,),  # ccxt кидает свои исключения от Exception; при желании сузить
        )
        def _do():
            t0 = time.perf_counter()
            try:
                res = self.breaker.call(key, fn, *args, timeout=timeout, **kwargs)
                metrics.observe("broker_latency_seconds", time.perf_counter() - t0, {"op": key, "result": "ok"})
                return res
            except CircuitOpenError as e:
                metrics.inc("broker_circuit_short_total", {"op": key})
                raise TransientExchangeError(str(e))
            except Exception as e:
                # простая классификация: HTTP 5xx/429 → Transient, остальное → Permanent
                msg = str(e).lower()
                transient = any(tok in msg for tok in ("429", "timed out", "timeout", "temporarily", "server error", "5"))
                metrics.observe("broker_latency_seconds", time.perf_counter() - t0, {"op": key, "result": "err"})
                if transient:
                    raise TransientExchangeError(str(e))
                raise PermanentExchangeError(str(e))

        return _do()

    # -------------------------- Реализация интерфейса --------------------------

    @rate_limit(key=lambda self, symbol, timeframe, limit: f"{self.exchange_name}:ohlcv", max_calls=60, window_seconds=60.0)
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        ex_symbol = self._ex_symbol(symbol)
        key = f"{self.exchange_name}.fetch_ohlcv"
        data = self._wrap_call(key, self.client.fetch_ohlcv, ex_symbol, timeframe, limit, _retries=3)
        # ccxt возвращает список списков [ms, o, h, l, c, v]
        return data

    @rate_limit(key=lambda self, symbol: f"{self.exchange_name}:ticker", max_calls=120, window_seconds=60.0)
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        ex_symbol = self._ex_symbol(symbol)
        key = f"{self.exchange_name}.fetch_ticker"
        return self._wrap_call(key, self.client.fetch_ticker, ex_symbol, _retries=2)

    @rate_limit(key=lambda self, symbol, type_, side, amount, price=None, **kw: f"{self.exchange_name}:orders", max_calls=60, window_seconds=60.0)
    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Optional[Decimal] = None,
        *,
        idempotency_key: str | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        ex_symbol = self._ex_symbol(symbol)
        key = f"{self.exchange_name}.create_order"

        params = {}
        if client_order_id:
            # bybit/okx/bn — разные ключи; ccxt нормализует как 'clientOrderId' для поддерживаемых
            params["clientOrderId"] = client_order_id

        # ccxt хочет float — аккуратнее приводим
        amount_f = float(amount)
        price_f = float(price) if price is not None else None

        order = self._wrap_call(
            key,
            self.client.create_order,
            ex_symbol,
            type_,
            side,
            amount_f,
            price_f,
            params,
            _retries=3,
        )
        return order

    @rate_limit(key=lambda self: f"{self.exchange_name}:balance", max_calls=60, window_seconds=60.0)
    def fetch_balance(self) -> Dict[str, Any]:
        key = f"{self.exchange_name}.fetch_balance"
        return self._wrap_call(key, self.client.fetch_balance, _retries=2)

    def cancel_order(self, order_id: str, *, symbol: str | None = None) -> Dict[str, Any]:
        key = f"{self.exchange_name}.cancel_order"
        if symbol:
            ex_symbol = self._ex_symbol(symbol)
            return self._wrap_call(key, self.client.cancel_order, order_id, ex_symbol, _retries=2)
        return self._wrap_call(key, self.client.cancel_order, order_id, _retries=2)

    def close(self) -> None:
        try:
            if hasattr(self.client, "close"):
                self.client.close()
        except Exception:
            pass
