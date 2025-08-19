# src/crypto_ai_bot/utils/retry.py
"""
Унифицированные ретраи для внешних вызовов (HTTP/CCXT и т.п.).
- sync/async декораторы: @retry(...) и @aretry(...)
- экспоненциальный backoff с опциональным jitter
- предикаты: is_retryable_http, is_retryable_ccxt, is_temporary_error
- необязательные метрики (utils.metrics) — не ломают код при отсутствии
"""
from __future__ import annotations

import asyncio
import random
import socket
import time
from functools import wraps
from typing import Any, Callable, Iterable, Optional

# optional metrics (не критично)
try:
    from crypto_ai_bot.utils import metrics  # type: ignore
    _inc = getattr(metrics, "inc", None)
    _observe = getattr(metrics, "observe", None)
except Exception:
    _inc = None
    _observe = None

# optional ccxt exceptions (могут отсутствовать в юнит-тестах)
try:
    import ccxt  # type: ignore
    _CCXT_NET = (
        getattr(ccxt, "NetworkError", tuple()),
        getattr(ccxt, "RequestTimeout", tuple()),
    )
    _CCXT_RATE = (
        getattr(ccxt, "RateLimitExceeded", tuple()),
        getattr(ccxt, "DDoSProtection", tuple()),
    )
    _CCXT_TEMP = (
        getattr(ccxt, "ExchangeNotAvailable", tuple()),
        getattr(ccxt, "OnMaintenance", tuple()),
        getattr(ccxt, "InvalidNonce", tuple()),
    )
except Exception:
    _CCXT_NET = tuple()
    _CCXT_RATE = tuple()
    _CCXT_TEMP = tuple()


# ------------ предикаты ------------
def is_retryable_http(exc: BaseException) -> bool:
    """Сетевые/временные ошибки: таймауты, разрывы, 5xx, 429 (если код доступен в исключении)."""
    if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror, socket.timeout)):
        return True
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status <= 599):
        return True
    return False


def is_retryable_ccxt(exc: BaseException) -> bool:
    """Типовые временные ошибки ccxt: сеть, лимиты, недоступность, nonce и т.п."""
    return isinstance(exc, _CCXT_NET + _CCXT_RATE + _CCXT_TEMP)


def is_temporary_error(exc: BaseException) -> bool:
    """Общий предикат по умолчанию (HTTP/сеть/ccxt)."""
    return is_retryable_http(exc) or is_retryable_ccxt(exc)


# ------------ механизм backoff ------------
def _backoff_seq(max_attempts: int, *, base: float, factor: float, jitter: bool) -> Iterable[float]:
    """Паузы между попытками: base, base*factor, ... (до max_attempts-1)."""
    delay = max(0.0, base)
    for _ in range(max(0, max_attempts - 1)):
        yield (delay + random.uniform(0, delay * 0.1)) if jitter and delay > 0 else delay
        delay *= max(1.0, factor)


# ------------ декораторы ------------
def retry(
    *,
    max_attempts: int = 5,
    backoff_base: float = 0.25,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_if: Callable[[BaseException], bool] = is_temporary_error,
    metric_prefix: Optional[str] = None,
):
    """Декоратор для синхронных функций."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempts = 0
            start = time.time()
            for backoff in _backoff_seq(max_attempts, base=backoff_base, factor=backoff_factor, jitter=jitter):
                try:
                    return fn(*args, **kwargs)
                except BaseException as e:  # noqa: BLE001
                    attempts += 1
                    if not retry_if(e) or attempts >= max_attempts:
                        if _inc and metric_prefix:
                            _inc(f"{metric_prefix}_retries_failed_total")
                        if _observe and metric_prefix:
                            _observe(f"{metric_prefix}_retries_duration_seconds", time.time() - start)
                        raise
                    if _inc and metric_prefix:
                        _inc(f"{metric_prefix}_retries_total")
                    time.sleep(backoff)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def aretry(
    *,
    max_attempts: int = 5,
    backoff_base: float = 0.25,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_if: Callable[[BaseException], bool] = is_temporary_error,
    metric_prefix: Optional[str] = None,
):
    """Декоратор для асинхронных функций."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempts = 0
            start = time.time()
            for backoff in _backoff_seq(max_attempts, base=backoff_base, factor=backoff_factor, jitter=jitter):
                try:
                    return await fn(*args, **kwargs)
                except BaseException as e:  # noqa: BLE001
                    attempts += 1
                    if not retry_if(e) or attempts >= max_attempts:
                        if _inc and metric_prefix:
                            _inc(f"{metric_prefix}_retries_failed_total")
                        if _observe and metric_prefix:
                            _observe(f"{metric_prefix}_retries_duration_seconds", time.time() - start)
                        raise
                    if _inc and metric_prefix:
                        _inc(f"{metric_prefix}_retries_total")
                    await asyncio.sleep(backoff)
            return await fn(*args, **kwargs)
        return wrapper
    return decorator


__all__ = [
    "retry",
    "aretry",
    "is_retryable_http",
    "is_retryable_ccxt",
    "is_temporary_error",
]
