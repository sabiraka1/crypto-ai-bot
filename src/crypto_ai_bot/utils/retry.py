from __future__ import annotations
import asyncio
import random
from typing import Any, Awaitable, Callable, Optional

async def async_retry(
    func: Callable[[], Awaitable[Any]],
    *,
    retries: int = 3,
    base_delay: float = 0.3,
    max_delay: float = 3.0,
    jitter: bool = True,
) -> Any:
    last_exc: Optional[Exception] = None
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

# Удобные обёртки поверх http_client
from crypto_ai_bot.utils.http_client import aget, apost

async def aget_retry(*args, **kwargs):
    return await async_retry(lambda: aget(*args, **kwargs))

async def apost_retry(*args, **kwargs):
    return await async_retry(lambda: apost(*args, **kwargs))
