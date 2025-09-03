from __future__ import annotations

from typing import Any

import httpx


# Ğ¡Ğ¸Ğ½Ñ…Ñ€Ğ¾Ğ½Ğ½Ñ‹Ğµ (Ğ¸ÑĞ¿Ğ¾Ğ»ÑŒĞ·Ğ¾Ğ²Ğ°Ñ‚ÑŒ Ñ€ĞµĞ´ĞºĞ¾; Ğ¿Ñ€ĞµĞ´Ğ¿Ğ¾Ñ‡Ñ‚Ğ¸Ñ‚ĞµĞ»ÑŒĞ½Ñ‹ async)
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


# ĞÑĞ¸Ğ½Ñ…Ñ€Ğ¾Ğ½Ğ½Ñ‹Ğµ â€” ÑÑ‚Ğ°Ğ½Ğ´Ğ°Ñ€Ñ‚ Ğ´Ğ»Ñ Ğ½Ğ°ÑˆĞµĞ³Ğ¾ ĞºĞ¾Ğ´Ğ°
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
