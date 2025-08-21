from __future__ import annotations
import time
import asyncio
import functools
from typing import Callable, TypeVar, Awaitable

T = TypeVar("T")


def retry(*, attempts: int = 5, backoff_base: float = 0.25, backoff_factor: float = 2.0):
    """Декоратор для синхронных функций с экспоненциальным повтором при исключениях."""
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            delay = backoff_base
            last_exc: Exception | None = None
            for i in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if i == attempts:
                        break
                    time.sleep(delay)
                    delay *= backoff_factor
            assert last_exc is not None
            raise last_exc
        return wrapper
    return deco


def retry_async(*, attempts: int = 5, backoff_base: float = 0.25, backoff_factor: float = 2.0):
    """Декоратор для асинхронных функций с экспоненциальным повтором при исключениях."""
    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            delay = backoff_base
            last_exc: Exception | None = None
            for i in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if i == attempts:
                        break
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
            assert last_exc is not None
            raise last_exc
        return wrapper
    return deco