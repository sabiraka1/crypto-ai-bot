from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import secrets
from typing import Any

# Публичный API сохраняем: async_retry, aget_retry, apost_retry


async def async_retry(
    func: Callable[[], Awaitable[Any]],
    *,
    retries: int = 3,
    base_delay: float = 0.3,
    max_delay: float = 3.0,
    jitter: bool = True,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    hard_timeout: float | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> Any:
    """
    Универсальный async-ретрай с экспоненциальной паузой и опциональным hard-timeout на попытку.
    Совместим с прежним контрактом: все новые параметры опциональны.

    :param func:        асинхронная функция без аргументов
    :param retries:     число попыток (минимум 1 = одна попытка без повторов)
    :param base_delay:  базовая задержка (сек) для первой паузы
    :param max_delay:   крышка для экспоненциального роста пауз
    :param jitter:      добавить случайный множитель в паузу (устойчивость к thundering herd)
    :param exceptions:  какие исключения перехватывать/повторять
    :param hard_timeout:жёсткий таймаут на одну попытку (сек); None = без лимита
    :param on_retry:    колбэк (attempt, exc, sleep_seconds) перед сном
    """
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            if hard_timeout and hard_timeout > 0:
                async with asyncio.timeout(hard_timeout):
                    return await func()
            return await func()
        except Exception as e:
            # не ретраим чужие типы исключений
            if not isinstance(e, exceptions) or attempt >= attempts:
                raise

            # capped exponential backoff
            delay = min(float(max_delay), float(base_delay) * (2 ** (attempt - 1)))
            if jitter:
                # крипто-надёжный джиттер: множитель в [0.5, 1.5)
                m = 0.5 + (secrets.randbelow(1000) / 1000.0)  # избегаем ruff S311
                delay *= m
            if on_retry:
                try:
                    on_retry(attempt, e, delay)
                except Exception:
                    # не позволяем колбэку сломать ретрай
                    pass
            await asyncio.sleep(delay)


# Оставляем удобные хелперы для http_client (как было)
from crypto_ai_bot.utils.http_client import aget, apost  # noqa: E402


async def aget_retry(*args: Any, **kwargs: Any) -> Any:
    return await async_retry(lambda: aget(*args, **kwargs))


async def apost_retry(*args: Any, **kwargs: Any) -> Any:
    return await async_retry(lambda: apost(*args, **kwargs))
