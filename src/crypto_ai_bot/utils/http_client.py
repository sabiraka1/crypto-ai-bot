from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

import httpx  # type: ignore

from .logging import get_logger
from .retry import retry  # если есть общий декоратор ретраев
from .circuit_breaker import CircuitBreaker  # если есть общий CB; иначе можно заглушить


_log = get_logger("utils.http")
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)  # общие таймауты на запрос


# --- Пул/синглтон клиента -----------------------------------------------------

_client_lock = asyncio.Lock()
_client: Optional[httpx.AsyncClient] = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, http2=True)
    return _client


# --- Circuit Breaker (опционально подключаем) --------------------------------

# Если общий CircuitBreaker недоступен — можно временно заменить на no-op:
_cb = CircuitBreaker(name="http", fail_max=5, reset_timeout=30) if "CircuitBreaker" in globals() else None


@asynccontextmanager
async def _cb_context() -> AsyncIterator[None]:
    if _cb is None:
        yield
        return
    with _cb:
        yield


# --- API: GET/POST ------------------------------------------------------------

@retry(  # повторные попытки на временные ошибки сети
    exceptions=(httpx.TransportError, httpx.ReadTimeout),
    tries=3,
    delay=0.25,
    backoff=2.0,
    jitter=0.1,
)
async def aget(url: str, *, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
    async with _cb_context():
        client = await _get_client()
        resp = await client.get(url, headers=headers, params=params)
        return resp


@retry(
    exceptions=(httpx.TransportError, httpx.ReadTimeout),
    tries=3,
    delay=0.25,
    backoff=2.0,
    jitter=0.1,
)
async def apost(url: str, *, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    async with _cb_context():
        client = await _get_client()
        resp = await client.post(url, json=json, data=data, headers=headers)
        return resp


# --- Graceful shutdown клиента ------------------------------------------------

async def aclose() -> None:
    """Закрывает общий AsyncClient (например, при graceful shutdown)."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
