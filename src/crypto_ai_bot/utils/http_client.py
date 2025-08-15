# -*- coding: utf-8 -*-

"""
utils/http_client.py
====================
Ğ•Ğ´Ğ¸Ğ½Ñ‹Ğ¹ HTTPâ€‘ĞºĞ»Ğ¸ĞµĞ½Ñ‚ Ğ´Ğ»Ñ Ğ¿Ñ€Ğ¾ĞµĞºÑ‚Ğ°: Ñ‚Ğ°Ğ¹Ğ¼Ğ°ÑƒÑ‚Ñ‹, Ñ€ĞµÑ‚Ñ€Ğ°Ğ¸, rateâ€‘limit, Ğ¿ÑƒĞ»Ñ‹ ÑĞ¾ĞµĞ´Ğ¸Ğ½ĞµĞ½Ğ¸Ğ¹, JSON-Ñ…ĞµĞ»Ğ¿ĞµÑ€Ñ‹.
Ğ˜ÑĞ¿Ğ¾Ğ»ÑŒĞ·ÑƒĞµÑ‚ÑÑ Ğ²Ğ¼ĞµÑÑ‚Ğ¾ Ğ¿Ñ€ÑĞ¼Ñ‹Ñ… `requests.get/post` Ğ²Ğ¾ Ğ²ÑĞµÑ… Ğ¼ĞµÑÑ‚Ğ°Ñ… (Telegram, Ğ¿Ñ€Ğ¾Ğ²Ğ°Ğ¹Ğ´ĞµÑ€Ñ‹, Ğ²Ğ½ĞµÑˆĞ½Ğ¸Ğµ API).

ĞšĞ»ÑÑ‡ĞµĞ²Ñ‹Ğµ Ñ„Ğ¸Ñ‡Ğ¸:
- Retry Ñ ÑĞºÑĞ¿Ğ¾Ğ½ĞµĞ½Ñ†Ğ¸Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¼ backoff (idempotent Ğ¼ĞµÑ‚Ğ¾Ğ´Ñ‹ Ğ¸ 429/5xx)
- Ğ¢Ğ°Ğ¹Ğ¼Ğ°ÑƒÑ‚Ñ‹/Ñ€ĞµÑ‚Ñ€Ğ°Ğ¸/Ğ»Ğ¸Ğ¼Ğ¸Ñ‚Ñ‹ Ğ±ĞµÑ€ÑƒÑ‚ÑÑ Ğ¸Ğ· Settings (Ğ¾Ğ´Ğ½Ğ° Ñ‚Ğ¾Ñ‡ĞºĞ° Ğ¿Ñ€Ğ°Ğ²Ğ´Ñ‹)
- RateLimiter (token bucket) Ğ½Ğ° ĞºĞ»Ğ¸ĞµĞ½Ñ‚ (QPS)
- ĞŸÑƒĞ»Ñ‹ ÑĞ¾ĞµĞ´Ğ¸Ğ½ĞµĞ½Ğ¸Ğ¹ requests (ÑƒĞ¼ĞµĞ½ÑŒÑˆĞ°ÑÑ‚ Ğ·Ğ°Ñ‚Ñ€Ğ°Ñ‚Ñ‹ Ğ½Ğ° TCP/TLS)
- Ğ£Ğ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğµ get_json/post_json, post_multipart (Ğ´Ğ»Ñ Telegram Ñ„Ğ¾Ñ‚Ğ¾)
- Ğ›Ñ‘Ğ³ĞºĞ¸Ğµ Ñ…ÑƒĞºĞ¸ Ğ´Ğ»Ñ Ğ¼ĞµÑ‚Ñ€Ğ¸Ğº (hit/error/latency) â€” no-op Ğ¿Ğ¾ ÑƒĞ¼Ğ¾Ğ»Ñ‡Ğ°Ğ½Ğ¸Ñ
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ĞĞ°ÑÑ‚Ñ€Ğ¾Ğ¹ĞºĞ¸ Ğ¿Ñ€Ğ¾ĞµĞºÑ‚Ğ°
try:
    from crypto_ai_bot.core.settings import Settings
except Exception:  # pragma: no cover
    # fallback Ğ´Ğ»Ñ Ñ€Ğ°Ğ½Ğ½Ğ¸Ñ… ÑÑ‚Ğ°Ğ´Ğ¸Ğ¹/Ñ‚ĞµÑÑ‚Ğ¾Ğ²
    class Settings:  # type: ignore
        @staticmethod
        def build():
            class _S:
                HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))
                HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
                HTTP_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.5"))
                HTTP_QPS = float(os.getenv("HTTP_QPS", "5"))
                HTTP_POOL_SIZE = int(os.getenv("HTTP_POOL_SIZE", "10"))
                HTTP_PROXY = os.getenv("HTTP_PROXY")
                HTTPS_PROXY = os.getenv("HTTPS_PROXY")
            return _S()


logger = logging.getLogger(__name__)


# â”€â”€ ĞœĞµÑ‚Ñ€Ğ¸ĞºĞ¸ (no-op Ğ¿Ğ¾ ÑƒĞ¼Ğ¾Ğ»Ñ‡Ğ°Ğ½Ğ¸Ñ, Ğ¼Ğ¾Ğ¶Ğ½Ğ¾ Ğ¿ĞµÑ€ĞµĞ¾Ğ¿Ñ€ĞµĞ´ĞµĞ»Ğ¸Ñ‚ÑŒ Ğ¸Ğ· monitoring) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class _Metrics:
    hit: Callable[[str, float, int], None] = staticmethod(lambda name, dur, status: None)
    error: Callable[[str, float, BaseException], None] = staticmethod(lambda name, dur, err: None)


metrics = _Metrics()


# â”€â”€ Rate Limiter (token bucket) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class RateLimiter:
    def __init__(self, qps: float) -> None:
        self.qps = max(0.1, float(qps))
        self.bucket = self.qps
        self.last = time.time()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            now = time.time()
            self.bucket = min(self.qps, self.bucket + (now - self.last) * self.qps)
            self.last = now
            if self.bucket < 1.0:
                # sleep Ğ´Ğ¾ 1 Ñ‚Ğ¾ĞºĞµĞ½Ğ°
                time.sleep((1.0 - self.bucket) / self.qps)
                self.bucket = 0.0
            else:
                self.bucket -= 1.0


# â”€â”€ ĞšĞ¾Ğ½Ñ„Ğ¸Ğ³ ĞºĞ»Ğ¸ĞµĞ½Ñ‚Ğ° (Ğ¸Ğ· Settings) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@dataclass(frozen=True)
class HttpConfig:
    timeout: float = 8.0
    retries: int = 2
    backoff: float = 0.5
    qps: float = 5.0
    pool_size: int = 10
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None

    @staticmethod
    def from_settings(cfg: Any) -> "HttpConfig":
        return HttpConfig(
            timeout=float(getattr(cfg, "HTTP_TIMEOUT", 8.0)),
            retries=int(getattr(cfg, "HTTP_RETRIES", 2)),
            backoff=float(getattr(cfg, "HTTP_BACKOFF", 0.5)),
            qps=float(getattr(cfg, "HTTP_QPS", 5.0)),
            pool_size=int(getattr(cfg, "HTTP_POOL_SIZE", 10)),
            http_proxy=getattr(cfg, "HTTP_PROXY", None),
            https_proxy=getattr(cfg, "HTTPS_PROXY", None),
        )


# â”€â”€ ĞšĞ»Ğ¸ĞµĞ½Ñ‚ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class HttpClient:
    def __init__(
        self,
        base_url: str | None = None,
        config: HttpConfig | None = None,
        session: Optional[requests.Session] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        cfg = config or HttpConfig.from_settings(Settings.build())
        self.config = cfg
        self.rl = RateLimiter(cfg.qps)

        self.s = session or requests.Session()

        # Retry policy (idempotent Ğ¼ĞµÑ‚Ğ¾Ğ´Ñ‹ Ğ¸ 429/5xx)
        retry = Retry(
            total=cfg.retries,
            backoff_factor=cfg.backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=cfg.pool_size,
            pool_maxsize=cfg.pool_size,
        )
        self.s.mount("http://", adapter)
        self.s.mount("https://", adapter)

        # ĞŸÑ€Ğ¾ĞºÑĞ¸, ĞµÑĞ»Ğ¸ Ğ·Ğ°Ğ´Ğ°Ğ½Ñ‹
        self.s.proxies = {
            k: v
            for k, v in {
                "http": cfg.http_proxy,
                "https": cfg.https_proxy,
            }.items()
            if v
        }

        # Ğ‘Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ Ğ·Ğ°Ğ³Ğ¾Ğ»Ğ¾Ğ²ĞºĞ¸
        self.headers = {"User-Agent": "crypto-ai-bot/1.0"}
        if default_headers:
            self.headers.update(default_headers)

    # â”€â”€ Ğ’ÑĞ¿Ğ¾Ğ¼Ğ¾Ğ³Ğ°Ñ‚ĞµĞ»ÑŒĞ½Ğ¾Ğµ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _url(self, path_or_url: str) -> str:
        if self.base_url and not path_or_url.startswith(("http://", "https://")):
            return f"{self.base_url}/{path_or_url.lstrip('/')}"
        return path_or_url

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> requests.Response:
        self.rl.acquire()
        t0 = time.time()
        full_url = self._url(url)
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)

        try:
            resp = self.s.request(method.upper(), full_url, headers=hdrs, timeout=timeout or self.config.timeout, **kwargs)
            dur = time.time() - t0
            metrics.hit(method.upper(), dur, getattr(resp, "status_code", -1))
            logger.debug("%s %s -> %s in %.3fs", method.upper(), full_url, resp.status_code, dur)
            return resp
        except Exception as e:
            dur = time.time() - t0
            metrics.error(method.upper(), dur, e)
            logger.warning("%s %s failed in %.3fs: %r", method.upper(), full_url, dur, e)
            raise

    # â”€â”€ ĞŸÑƒĞ±Ğ»Ğ¸Ñ‡Ğ½Ñ‹Ğµ Ğ¼ĞµÑ‚Ğ¾Ğ´Ñ‹ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("HEAD", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("DELETE", url, **kwargs)

    def post(self, url: str, data: Any = None, json_body: Any = None, **kwargs: Any) -> requests.Response:
        if json_body is not None:
            kwargs.setdefault("headers", {})
            kwargs["headers"].setdefault("Content-Type", "application/json")
            return self._request("POST", url, data=json.dumps(json_body), **kwargs)
        return self._request("POST", url, data=data, **kwargs)

    # JSON helpers
    def get_json(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        r = self.get(url, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    def post_json(self, url: str, payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        r = self.post(url, json_body=payload, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    # Multipart helper (Ğ´Ğ»Ñ Telegram Ñ„Ğ¾Ñ‚Ğ¾/Ğ´Ğ¾ĞºÑƒĞ¼ĞµĞ½Ñ‚Ğ¾Ğ²)
    def post_multipart(self, url: str, files: Dict[str, Tuple[str, bytes, str]], data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        r = self._request("POST", url, files=files, data=data or {}, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    # Close (Ğ´Ğ»Ñ ÑĞ²Ğ½Ğ¾Ğ³Ğ¾ Ğ·Ğ°Ğ²ĞµÑ€ÑˆĞµĞ½Ğ¸Ñ Ğ² Ñ‚ĞµÑÑ‚Ğ°Ñ…/Ğ²Ğ¾Ñ€ĞºĞµÑ€Ğ°Ñ…)
    def close(self) -> None:
        try:
            self.s.close()
        except Exception:
            pass


# â”€â”€ Singleton Ñ„Ğ°Ğ±Ñ€Ğ¸ĞºĞ° â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_default_client: Optional[HttpClient] = None


def get_http_client(base_url: str | None = None) -> HttpClient:
    """
    Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ singleton-ĞºĞ»Ğ¸ĞµĞ½Ñ‚ (Ğ±ĞµĞ· base_url). Ğ”Ğ»Ñ Ñ€Ğ°Ğ·Ğ½Ñ‹Ñ… base_url Ğ¼Ğ¾Ğ¶Ğ½Ğ¾
    ÑĞ¾Ğ·Ğ´Ğ°Ğ²Ğ°Ñ‚ÑŒ Ğ¾Ñ‚Ğ´ĞµĞ»ÑŒĞ½Ñ‹Ğµ ÑĞºĞ·ĞµĞ¼Ğ¿Ğ»ÑÑ€Ñ‹ `HttpClient(base_url=...)`.
    """
    global _default_client
    if base_url:
        return HttpClient(base_url=base_url)  # Ğ¾Ñ‚Ğ´ĞµĞ»ÑŒĞ½Ñ‹Ğ¹ ÑĞºĞ·ĞµĞ¼Ğ¿Ğ»ÑÑ€ Ğ¿Ğ¾Ğ´ ĞºĞ¾Ğ½ĞºÑ€ĞµÑ‚Ğ½Ñ‹Ğ¹ API
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client


__all__ = ["HttpClient", "HttpConfig", "RateLimiter", "get_http_client", "metrics"]

