## `utils/retry.py`
from __future__ import annotations
import asyncio
import random
import time
from functools import wraps
from typing import Callable, Optional, Tuple, Type
from .exceptions import TransientError
from .circuit_breaker import CircuitBreaker
__all__ = ["retry", "retry_async"]
_DEFAULT_EXC: Tuple[Type[BaseException], ...] = (TransientError, TimeoutError, ConnectionError)
def _compute_sleep(attempt: int, base: float, factor: float, jitter: float, max_sleep: float) -> float:
    delay = base * (factor ** (attempt - 1))
    if jitter > 0:
        delay += random.uniform(0, jitter)
    return min(delay, max_sleep)
def retry(*, attempts: int = 5, backoff_base: float = 0.25, backoff_factor: float = 2.0,
          jitter: float = 0.1, max_sleep: float = 5.0, retry_on: Tuple[Type[BaseException], ...] = _DEFAULT_EXC,
          breaker: Optional[CircuitBreaker] = None):
    """Retry decorator for sync functions with exponential backoff and optional circuit breaker."""
    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 1
            last_exc: Optional[BaseException] = None
            while attempt <= attempts:
                try:
                    if breaker is not None:
                        return breaker.run(fn, *args, **kwargs)
                    return fn(*args, **kwargs)
                except retry_on as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt == attempts:
                        raise
                    sleep_s = _compute_sleep(attempt, backoff_base, backoff_factor, jitter, max_sleep)
                    time.sleep(sleep_s)
                    attempt += 1
            if last_exc is not None:
                raise last_exc
        return wrapper
    return decorator
def retry_async(*, attempts: int = 5, backoff_base: float = 0.25, backoff_factor: float = 2.0,
                jitter: float = 0.1, max_sleep: float = 5.0, retry_on: Tuple[Type[BaseException], ...] = _DEFAULT_EXC,
                breaker: Optional[CircuitBreaker] = None):
    """Retry decorator for async functions with exponential backoff and optional circuit breaker."""
    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            attempt = 1
            last_exc: Optional[BaseException] = None
            while attempt <= attempts:
                try:
                    if breaker is not None:
                        return await breaker.run_async(fn, *args, **kwargs)
                    return await fn(*args, **kwargs)
                except retry_on as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt == attempts:
                        raise
                    sleep_s = _compute_sleep(attempt, backoff_base, backoff_factor, jitter, max_sleep)
                    await asyncio.sleep(sleep_s)
                    attempt += 1
            if last_exc is not None:
                raise last_exc
        return wrapper
    return decorator
