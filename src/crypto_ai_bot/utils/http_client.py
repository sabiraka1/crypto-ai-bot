# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations

from typing import Optional, Dict, Any

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class HttpClient:
    """
    Минимальный HTTP-клиент с таймаутом. Без ретраев, чтобы не тащить внешние зависимости.
    """
    def __init__(self, default_timeout: float = 5.0):
        if requests is None:
            raise RuntimeError("requests is not installed")
        self._s = requests.Session()
        self._timeout = float(default_timeout)

    def get(self, url: str, *, timeout: Optional[float] = None, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        t = self._timeout if timeout is None else float(timeout)
        r = self._s.get(url, params=params, headers=headers, timeout=t)
        r.raise_for_status()
        return r

    def post(self, url: str, *, timeout: Optional[float] = None, json: Optional[Any] = None, data: Optional[Any] = None, headers: Optional[Dict[str, str]] = None):
        t = self._timeout if timeout is None else float(timeout)
        r = self._s.post(url, json=json, data=data, headers=headers, timeout=t)
        r.raise_for_status()
        return r


def get_http_client(timeout: float = 5.0) -> HttpClient:
    return HttpClient(default_timeout=timeout)
