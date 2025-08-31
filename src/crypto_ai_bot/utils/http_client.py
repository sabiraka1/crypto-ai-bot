from __future__ import annotations

from typing import Any

import httpx


# Синхронные (использовать редко; предпочтительны async)
def get(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    return httpx.get(url, timeout=timeout, headers=headers, params=params)


def post(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.post(url, json=json, data=data, timeout=timeout, headers=headers)


# Асинхронные — стандарт для нашего кода
async def aget(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        return await client.get(url, params=params)


async def apost(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        return await client.post(url, json=json, data=data)
