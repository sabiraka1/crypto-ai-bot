"""
Retry utilities with exponential backoff.
Простая, надёжная реализация для повторных попыток.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, TypeVar, ParamSpec, Tuple

T = TypeVar("T")
P = ParamSpec("P")

__all__ = [
    "async_retry",
    "sync_retry",
    "RetryConfig",
    "FAST_RETRY",
    "API_RETRY",
    "CRITICAL_RETRY",
]


def _validate_params(
    *,
    max_attempts: int,
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
) -> None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if initial_delay < 0:
        raise ValueError("initial_delay must be >= 0")
    if max_delay < 0:
        raise ValueError("max_delay must be >= 0")
    if exponential_base <= 0:
        raise ValueError("exponential_base must be > 0")


def _compute_delay(
    attempt: int,
    *,
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
    jitter: bool,
) -> float:
    # attempt начинается с 0 → на первой паузе delay = initial_delay
    delay = min(initial_delay * (exponential_base ** attempt), max_delay)
    if jitter:
        # Full jitter в диапазоне [0.5, 1.5)
        delay *= (0.5 + random.random())
    # защита от отрицательных/NaN
    if not (delay >= 0):
        return 0.0
    return delay


async def async_retry(
    func: Callable[P, Awaitable[T]],
    *args: P.args,
    max_attempts: int = 3,
    initial_delay: float = 0.5,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[type[Exception], ...] = (Exception,),
    **kwargs: P.kwargs,
) -> T:
    """
    Асинхронный retry с exponential backoff.

    Args:
        func: Асинхронная функция для выполнения
        *args, **kwargs: Аргументы функции
        max_attempts: Максимальное количество попыток (>=1)
        initial_delay: Начальная задержка между попытками (сек)
        max_delay: Максимальная задержка между попытками (сек)
        exponential_base: База экспоненты для роста задержки
        jitter: Добавлять ли случайный разброс к задержке
        exceptions: Исключения, при которых делаем повтор

    Returns:
        Результат успешного выполнения func

    Raises:
        Последнее исключение после исчерпания попыток.
        asyncio.CancelledError никогда не ретраится — пробрасывается сразу.
    """
    _validate_params(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
    )

    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            # Важно: отмена задач не ретраится
            if isinstance(e, asyncio.CancelledError):
                raise
            last_exception = e

            # Последняя попытка — пробрасываем исключение
            if attempt == max_attempts - 1:
                raise

            delay = _compute_delay(
                attempt=attempt,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
            )
            await asyncio.sleep(delay)

    # Теоретически недостижимо
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry state (async)")


def sync_retry(
    func: Callable[P, T],
    *args: P.args,
    max_attempts: int = 3,
    initial_delay: float = 0.5,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[type[Exception], ...] = (Exception,),
    **kwargs: P.kwargs,
) -> T:
    """
    Синхронный retry с exponential backoff.

    Args:
        func: Синхронная функция для выполнения
        *args, **kwargs: Аргументы функции
        max_attempts: Максимальное количество попыток (>=1)
        initial_delay: Начальная задержка между попытками (сек)
        max_delay: Максимальная задержка между попытками (сек)
        exponential_base: База экспоненты для роста задержки
        jitter: Добавлять ли случайный разброс к задержке
        exceptions: Исключения, при которых делаем повтор
    """
    _validate_params(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
    )

    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt == max_attempts - 1:
                raise

            delay = _compute_delay(
                attempt=attempt,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
            )
            time.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry state (sync)")


class RetryConfig:
    """
    Конфигурация для retry-политик.
    Позволяет создавать преднастроенные retry-вызовы.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.5,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        exceptions: Tuple[type[Exception], ...] = (Exception,),
    ):
        _validate_params(
            max_attempts=max_attempts,
            initial_delay=initial_delay,
            max_delay=max_delay,
            exponential_base=exponential_base,
        )
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.exceptions = exceptions

    async def async_execute(self, func: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
        """Выполнить асинхронную функцию с retry-политикой."""
        return await async_retry(
            func,
            *args,
            max_attempts=self.max_attempts,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
            exceptions=self.exceptions,
            **kwargs,
        )

    def sync_execute(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Выполнить синхронную функцию с retry-политикой."""
        return sync_retry(
            func,
            *args,
            max_attempts=self.max_attempts,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
            exceptions=self.exceptions,
            **kwargs,
        )


# Преднастроенные конфигурации для разных случаев
FAST_RETRY = RetryConfig(
    max_attempts=3,
    initial_delay=0.1,
    max_delay=1.0,
)

API_RETRY = RetryConfig(
    max_attempts=5,
    initial_delay=0.5,
    max_delay=10.0,
)

CRITICAL_RETRY = RetryConfig(
    max_attempts=10,
    initial_delay=1.0,
    max_delay=30.0,
)
