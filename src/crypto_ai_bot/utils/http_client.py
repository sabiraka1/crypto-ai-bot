# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union

try:
    import httpx
except Exception as exc:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SEC", "10"))

class HttpClientError(RuntimeError):
    pass

async def get_json(url: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    if httpx is None:
        raise HttpClientError("httpx is not installed")
    t = timeout or _DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=t) as cli:
        r = await cli.get(url)
        _raise_for_status(r)
        return _to_json(r)

async def post_json(url: str, payload: Union[Dict[str, Any], list], *, timeout: Optional[float] = None) -> Dict[str, Any]:
    if httpx is None:
        raise HttpClientError("httpx is not installed")
    t = timeout or _DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=t) as cli:
        r = await cli.post(url, json=payload)
        _raise_for_status(r)
        return _to_json(r)

def _raise_for_status(r: "httpx.Response") -> None:
    if r.status_code >= 400:
        txt = r.text[:500] if hasattr(r, "text") else ""
        raise HttpClientError(f"HTTP {r.status_code}: {txt}")

def _to_json(r: "httpx.Response") -> Dict[str, Any]:
    ctype = r.headers.get("content-type", "")
    if "application/json" in ctype.lower():
        try:
            return r.json()  # type: ignore[return-value]
        except Exception:
            pass
    return {"status_code": r.status_code, "text": r.text}
