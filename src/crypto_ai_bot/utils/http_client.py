# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import requests

from .retry import retry
from . import metrics


class _RateLimiter:
    """
    Простой rate-limit: не чаще N запросов в секунду (глобально).
    """
    def __init__(self, per_sec: Optional[float]):
        self.per_sec = per_sec
        self._lock = threading.Lock()
        self._next_ts = 0.0

    def acquire(self):
        if not self.per_sec or self.per_sec <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_ts - now
            if wait > 0:
                time.sleep(wait)
            # следующий слот
            self._next_ts = max(now, self._next_ts) + (1.0 / self.per_sec)


class HttpClient:
    def __init__(
        self,
        *,
        timeout_sec: float = 10.0,
        retries: int = 2,
        backoff_base: float = 0.2,
        jitter: float = 0.1,
        rate_limit_per_sec: Optional[float] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.session = requests.Session()
        self.timeout = float(timeout_sec)
        self.retries = int(retries)
        self.backoff_base = float(backoff_base)
        self.jitter = float(jitter)
        self.rl = _RateLimiter(rate_limit_per_sec)
        self.default_headers = default_headers or {}

    def _labels(self, url: str, code: int | None = None) -> Dict[str, str]:
        host = ""
        try:
            host = requests.utils.urlparse(url).netloc or ""
        except Exception:
            pass
        lab = {"host": host}
        if code is not None:
            lab["code"] = str(code)
        return lab

    @retry()
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self.rl.acquire()
        headers = dict(self.default_headers)
        headers.update(kwargs.pop("headers", {}) or {})
        timeout = kwargs.pop("timeout", self.timeout)
        start = time.perf_counter()
        try:
            resp = self.session.request(method, url, headers=headers, timeout=timeout, **kwargs)
            metrics.inc("http_client_requests_total", self._labels(url, resp.status_code))
            return resp
        except Exception as e:
            metrics.inc("http_client_requests_total", self._labels(url, 599))
            raise e
        finally:
            dur = time.perf_counter() - start
            metrics.observe("http_client_latency_seconds", dur, self._labels(url))

    def get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        r = self._request("GET", url, params=params or {}, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def post_json(self, url: str, *, json: Any, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        r = self._request("POST", url, json=json, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def post_multipart(self, url: str, *, files: Dict[str, Any], data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        r = self._request("POST", url, files=files, data=data or {}, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()


# Фабрика без чтения ENV (по правилам); при желании можно передавать настройки вручную
def get_http_client(
    *,
    timeout_sec: float = 10.0,
    retries: int = 2,
    backoff_base: float = 0.2,
    jitter: float = 0.1,
    rate_limit_per_sec: Optional[float] = None,
    default_headers: Optional[Dict[str, str]] = None,
) -> HttpClient:
    return HttpClient(
        timeout_sec=timeout_sec,
        retries=retries,
        backoff_base=backoff_base,
        jitter=jitter,
        rate_limit_per_sec=rate_limit_per_sec,
        default_headers=default_headers,
    )
