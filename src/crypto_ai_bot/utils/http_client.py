from __future__ import annotations

from typing import Any, Dict, Optional, Union

import httpx


# Синхронные вызовы (по возможности используем только в верхних слоях)
def get(url: str, *, timeout: float = 30.0, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
    return httpx.get(url, timeout=timeout, headers=headers, params=params)

def post(url: str, *, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None, timeout: float = 30.0,
         headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    return httpx.post(url, json=json, data=data, timeout=timeout, headers=headers)


# Асинхронные вызовы — предпочтительнее
async def aget(url: str, *, timeout: float = 30.0, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        return await client.get(url, params=params)

async def apost(url: str, *, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None, timeout: float = 30.0,
                headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        return await client.post(url, json=json, data=data)
