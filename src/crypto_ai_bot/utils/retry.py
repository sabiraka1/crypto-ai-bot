# src/crypto_ai_bot/utils/retry.py
from __future__ import annotations

import asyncio
import random
import time
from functools import wraps
from typing import Callable, Tuple, Type


def retry(
    *,
    retries: int = 2,
    backoff_base: float = 0.2,
    jitter: float = 0.1,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
):
    """
    Декоратор для повторов (sync/async) с экспоненциальным бэкоффом и джиттером.
    """
    def deco(fn):
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def aw(*args, **kwargs):
                attempt = 0
                while True:
                    try:
                        return await fn(*args, **kwargs)
                    except retry_on as e:
                        if attempt >= retries:
                            raise
                        delay = (backoff_base * (2 ** attempt)) + random.uniform(0, jitter)
                        if on_retry:
                            on_retry(attempt + 1, e)
                        await asyncio.sleep(delay)
                        attempt += 1
            return aw
        else:
            @wraps(fn)
            def sw(*args, **kwargs):
                attempt = 0
                while True:
                    try:
                        return fn(*args, **kwargs)
                    except retry_on as e:
                        if attempt >= retries:
                            raise
                        delay = (backoff_base * (2 ** attempt)) + random.uniform(0, jitter)
                        if on_retry:
                            on_retry(attempt + 1, e)
                        time.sleep(delay)
                        attempt += 1
            return sw
    return deco
