# -*- coding: utf-8 -*-

"""
utils/http_client.py
====================
Единый HTTP‑клиент для проекта: таймауты, ретраи, rate‑limit, пулы соединений, JSON-хелперы.
Используется вместо прямых `requests.get/post` во всех местах (Telegram, провайдеры, внешние API).

Ключевые фичи:
- Retry с экспоненциальным backoff (idempotent методы и 429/5xx)
- Таймауты/ретраи/лимиты берутся из Settings (одна точка правды)
- RateLimiter (token bucket) на клиент (QPS)
- Пулы соединений requests (уменьшают затраты на TCP/TLS)
- Унифицированные get_json/post_json, post_multipart (для Telegram фото)
- Лёгкие хуки для метрик (hit/error/latency) — no-op по умолчанию
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

# Настройки проекта
try:
    from crypto_ai_bot.core.settings import Settings
except Exception:  # pragma: no cover
    # fallback для ранних стадий/тестов
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


# ── Метрики (no-op по умолчанию, можно переопределить из monitoring) ───────────
class _Metrics:
    hit: Callable[[str, float, int], None] = staticmethod(lambda name, dur, status: None)
    error: Callable[[str, float, BaseException], None] = staticmethod(lambda name, dur, err: None)


metrics = _Metrics()


# ── Rate Limiter (token bucket) ────────────────────────────────────────────────
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
                # sleep до 1 токена
                time.sleep((1.0 - self.bucket) / self.qps)
                self.bucket = 0.0
            else:
                self.bucket -= 1.0


# ── Конфиг клиента (из Settings) ──────────────────────────────────────────────
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


# ── Клиент ────────────────────────────────────────────────────────────────────
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

        # Retry policy (idempotent методы и 429/5xx)
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

        # Прокси, если заданы
        self.s.proxies = {
            k: v
            for k, v in {
                "http": cfg.http_proxy,
                "https": cfg.https_proxy,
            }.items()
            if v
        }

        # Базовые заголовки
        self.headers = {"User-Agent": "crypto-ai-bot/1.0"}
        if default_headers:
            self.headers.update(default_headers)

    # ── Вспомогательное ────────────────────────────────────────────────────────
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

    # ── Публичные методы ───────────────────────────────────────────────────────
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

    # Multipart helper (для Telegram фото/документов)
    def post_multipart(self, url: str, files: Dict[str, Tuple[str, bytes, str]], data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        r = self._request("POST", url, files=files, data=data or {}, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    # Close (для явного завершения в тестах/воркерах)
    def close(self) -> None:
        try:
            self.s.close()
        except Exception:
            pass


# ── Singleton фабрика ─────────────────────────────────────────────────────────
_default_client: Optional[HttpClient] = None


def get_http_client(base_url: str | None = None) -> HttpClient:
    """
    Возвращает singleton-клиент (без base_url). Для разных base_url можно
    создавать отдельные экземпляры `HttpClient(base_url=...)`.
    """
    global _default_client
    if base_url:
        return HttpClient(base_url=base_url)  # отдельный экземпляр под конкретный API
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client


__all__ = ["HttpClient", "HttpConfig", "RateLimiter", "get_http_client", "metrics"]
