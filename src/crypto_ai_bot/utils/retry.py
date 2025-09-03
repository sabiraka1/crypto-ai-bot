from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any


async def async_retry(
    func: Callable[[], Awaitable[Any]],
    *,
    retries: int = 3,
    base_delay: float = 0.3,
    max_delay: float = 3.0,
    jitter: bool = True,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_exc = e
            delay = min(max_delay, base_delay * (2 ** attempt))
            if jitter:
                delay *= (0.5 + random.random())
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc

# Ğ£Ğ´Ğ¾Ğ±Ğ½Ñ‹Ğµ Ğ¾Ğ±Ñ‘Ñ€Ñ‚ĞºĞ¸ Ğ¿Ğ¾Ğ²ĞµÑ€Ñ… http_client
from crypto_ai_bot.utils.http_client import aget, apost


async def aget_retry(*args: Any, **kwargs: Any) -> Any:
    return await async_retry(lambda: aget(*args, **kwargs))

async def apost_retry(*args: Any, **kwargs: Any) -> Any:
    return await async_retry(lambda: apost(*args, **kwargs))