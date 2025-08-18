from __future__ import annotations
from typing import Any, Dict, Optional, Callable

import time
import math

from crypto_ai_bot.utils.rate_limiter import MultiLimiter
from crypto_ai_bot.utils.metrics import inc, gauge

# CCXT и типы ошибок
try:
    import ccxt
    from ccxt.base.errors import (
        DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, NetworkError,
        RequestTimeout, AuthenticationError, PermissionDenied,
        InvalidOrder, InsufficientFunds, OrderNotFound
    )
except Exception as e:  # pragma: no cover
    ccxt = None
    # Ошибки могут отсутствовать до установки ccxt


class CCXTExchange:
    """
    Адаптер под CCXT с:
    - enableRateLimit (встроенный)
    - доп. пер-методными лимитами (public/private read/write)
    - ретраями с экспонентой для временных ошибок
    - счётчиками 429/Retry и latency-метриками
    """

    def __init__(self, settings, bus=None, exchange_name: Optional[str] = None):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")

        self.cfg = settings
        self.bus = bus
        self.exchange_name = (exchange_name or getattr(settings, "EXCHANGE", "gateio")).lower()

        # --- инициализация CCXT ---
        ex_cls = getattr(ccxt, self.exchange_name, None)
        if ex_cls is None:
            raise ValueError(f"Unknown exchange for ccxt: {self.exchange_name}")

        opts = {
            "enableRateLimit": True,  # базовая защита CCXT
            "timeout": int(getattr(settings, "GATEIO_HTTP_TIMEOUT_MS", 5000)),
            "options": {
                # сюда можно добавить exchange-specific опции
                # "defaultType": "spot"   # на Gate.io это поведение CCXT корректно определяет по методу
            }
        }
        self.ccxt = ex_cls(opts)

        # ключи (если заданы)
        api_key = getattr(settings, "API_KEY", None) or getattr(settings, "GATEIO_API_KEY", None)
        api_secret = getattr(settings, "API_SECRET", None) or getattr(settings, "GATEIO_API_SECRET", None)
        password = getattr(settings, "API_PASSWORD", None) or getattr(settings, "GATEIO_API_PASSWORD", None)
        if api_key and api_secret:
            self.ccxt.apiKey = api_key
            self.ccxt.secret = api_secret
        if password:
            # для некоторых бирж требуется (на Gate.io обычно не нужно)
            self.ccxt.password = password

        # --- локальные пер-методные rate-limits (по умолчанию консервативные) ---
        self.limiter = MultiLimiter()
        self.limiter.set_bucket(
            "public_read",
            rpm=float(getattr(settings, "RATE_PUBLIC_RPM", 400.0)),
            burst=float(getattr(settings, "RATE_PUBLIC_BURST", 400.0)),
        )
        self.limiter.set_bucket(
            "private_read",
            rpm=float(getattr(settings, "RATE_PRIVATE_READ_RPM", 200.0)),
            burst=float(getattr(settings, "RATE_PRIVATE_READ_BURST", 200.0)),
        )
        self.limiter.set_bucket(
            "private_write",
            rpm=float(getattr(settings, "RATE_PRIVATE_WRITE_RPM", 120.0)),
            burst=float(getattr(settings, "RATE_PRIVATE_WRITE_BURST", 120.0)),
        )

        # --- retry/CB параметры ---
        self.max_retries = int(getattr(settings, "BROKER_RETRY_MAX", 5))
        self.base_sleep = float(getattr(settings, "BROKER_RETRY_BASE_SEC", 0.2))
        self.max_sleep  = float(getattr(settings, "BROKER_RETRY_MAX_SEC", 2.5))

    # -------------- публичные методы, совместимые с прежними вызовами --------------

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self._call(
            key="public_read",
            fn=lambda: self.ccxt.fetch_ticker(symbol),
            metric="broker_fetch_ticker"
        )

    def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        return self._call(
            key="private_read",
            fn=lambda: self.ccxt.fetch_order(order_id, symbol),
            metric="broker_fetch_order"
        )

    def create_order(self, *, symbol: str, type: str, side: str, amount: float) -> Dict[str, Any]:
        return self._call(
            key="private_write",
            fn=lambda: self.ccxt.create_order(symbol, type, side, amount),
            metric="broker_create_order"
        )

    # ---------------------------- внутренние утилиты ----------------------------

    def _call(self, *, key: str, fn: Callable[[], Any], metric: str) -> Any:
        """
        Обёртка: rate limit -> timed call -> retry по временным ошибкам -> метрики.
        """
        # локальный rate-limit
        if not self.limiter.acquire(key, tokens=1.0, timeout=float(getattr(self.cfg, "RATE_WAIT_TIMEOUT_SEC", 5.0))):
            inc("broker_rate_timeout", {"key": key, "ex": self.exchange_name})
            # как degrade: пробуем один раз без ожидания, но помечаем метрикой
        start = time.perf_counter()
        try:
            return self._retrying_call(fn, metric, key)
        finally:
            dur = time.perf_counter() - start
            gauge(f"{metric}_seconds", dur, {"ex": self.exchange_name, "key": key})

    def _retrying_call(self, fn: Callable[[], Any], metric: str, key: str) -> Any:
        """
        Экспоненциальный backoff для временных ошибок.
        """
        attempt = 0
        while True:
            try:
                out = fn()
                if out is None:
                    # странная деградация — считаем как ошибку сети
                    raise ExchangeNotAvailable("empty response")
                return out
            except Exception as e:
                attempt += 1
                cat = self._categorize_error(e)
                if cat == "rate":
                    inc("broker_http_429", {"ex": self.exchange_name, "key": key})
                elif cat == "temp":
                    inc("broker_retry_temp", {"ex": self.exchange_name, "key": key})
                elif cat == "perm":
                    inc("broker_error_perm", {"ex": self.exchange_name, "key": key, "type": e.__class__.__name__})
                    # постоянная ошибка — не ретраим
                    raise
                else:
                    inc("broker_error_unknown", {"ex": self.exchange_name, "key": key, "type": e.__class__.__name__})

                if cat in ("rate", "temp"):
                    if attempt > self.max_retries:
                        raise
                    # экспонента с джиттером
                    sleep_s = min(self.max_sleep, self.base_sleep * (2 ** (attempt - 1)))
                    sleep_s *= (1.0 + 0.25 * (attempt % 2))  # лёгкий джиттер
                    time.sleep(sleep_s)
                    continue
                # неизвестная/прочая — пробрасываем
                raise

    @staticmethod
    def _categorize_error(e: Exception) -> str:
        """
        'rate' -> 429/антиDDoS/лимиты
        'temp' -> временные сетевые/таймауты
        'perm' -> постоянные (аутентификация, неверные параметры, недостаточно средств)
        'other' -> всё остальное
        """
        # ccxt-специфичные классы
        if isinstance(e, (RateLimitExceeded, DDoSProtection)):
            return "rate"
        if isinstance(e, (ExchangeNotAvailable, NetworkError, RequestTimeout)):
            return "temp"
        if isinstance(e, (AuthenticationError, PermissionDenied, InvalidOrder, InsufficientFunds, OrderNotFound)):
            return "perm"
        # иногда биржи шлют plain HTTP-429/5xx через generic исключения
        msg = str(e).lower()
        if "429" in msg or "too many requests" in msg or "anti" in msg and "ddos" in msg:
            return "rate"
        if "timeout" in msg or "temporar" in msg or "temporarily" in msg or "unavailable" in msg:
            return "temp"
        if "invalid" in msg or "insufficient" in msg or "authentication" in msg or "permission" in msg:
            return "perm"
        return "other"
