from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

# --- необязательная телеметрия (не жёсткая зависимость) ---
try:
    from crypto_ai_bot.utils.metrics import inc, observe  # type: ignore
except Exception:  # noqa: BLE001

    def inc(*_a: Any, **_k: Any) -> None:  # type: ignore
        pass

    def observe(*_a: Any, **_k: Any) -> None:  # type: ignore
        pass


# ===================== ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ =====================


@dataclass
class TimeoutProfile:
    """Профиль таймаутов: структурированный httpx.Timeout + опциональный hard_timeout (сек)."""

    timeout: httpx.Timeout
    hard_timeout: float | None = None


@dataclass
class _GlobalConfig:
    max_concurrency: int | None = None
    proxies: dict[str, str] | str | None = None
    profiles: dict[str, TimeoutProfile] = field(default_factory=dict)

    def get_profile(self, name: str | None, fallback: float | httpx.Timeout | None) -> TimeoutProfile:
        if name and name in self.profiles:
            return self.profiles[name]
        return TimeoutProfile(_mk_timeout(fallback), None)


_CFG = _GlobalConfig()
_SEMA: asyncio.Semaphore | None = None
_CFG_LOCK = asyncio.Lock()


async def configure(
    *,
    max_concurrency: int | None = None,
    proxies: dict[str, str] | str | None = None,
    timeout_profiles: dict[str, float | httpx.Timeout | tuple[float | httpx.Timeout, float | None]]
    | None = None,
) -> None:
    """
    Глобальная настройка клиента:
      - max_concurrency: лимит одновременных запросов (None = без лимита)
      - proxies: форматы httpx (str | dict)
      - timeout_profiles: {"exchange":  (Timeout|float[, hard_timeout]), ...}
    Пример:
      await configure(
        max_concurrency=100,
        proxies={"https://": "http://user:pass@proxy:8080"},
        timeout_profiles={
          "exchange": (httpx.Timeout(5, read=15, write=10, pool=5), 20),
          "webhook":  5.0,
        },
      )
    """
    async with _CFG_LOCK:
        if max_concurrency is not None:
            global _SEMA
            _SEMA = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
            _CFG.max_concurrency = max_concurrency

        if proxies is not None:
            _CFG.proxies = proxies

        if timeout_profiles:
            profs: dict[str, TimeoutProfile] = {}
            for k, v in timeout_profiles.items():
                if isinstance(v, tuple):
                    base, hard = v
                    profs[k] = TimeoutProfile(_mk_timeout(base), float(hard) if hard else None)
                else:
                    profs[k] = TimeoutProfile(_mk_timeout(v), None)
            _CFG.profiles.update(profs)


# ===================== ВНУТРЕННИЕ ХЕЛПЕРЫ =====================


def _mk_timeout(t: float | httpx.Timeout | None) -> httpx.Timeout:
    """Структурированный timeout: разбиваем общий на фазы."""
    if isinstance(t, httpx.Timeout):
        return t
    total = float(t or 30.0)
    return httpx.Timeout(
        connect=min(10.0, total / 3),
        read=total,
        write=min(10.0, total / 2),
        pool=min(5.0, total / 2),
    )


def _should_retry_response(resp: httpx.Response) -> bool:
    """Повторяем на 429/5xx и некоторых облачных кодах."""
    if resp.status_code in (408, 425, 429, 500, 502, 503, 504):
        return True
    if 520 <= resp.status_code <= 527:
        return True
    return False


def _retry_after_delay(resp: httpx.Response) -> float | None:
    """Считываем Retry-After (секунды). Если дата — пропускаем (не парсим тяжело)."""
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        val = int(float(ra))
        return max(0.0, float(val))
    except Exception:  # noqa: BLE001
        return None


def _is_retryable_exc(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ),
    )


def _jitter(base: float, factor: float = 0.25) -> float:
    """exponential backoff jitter."""
    delta = base * factor
    return max(0.0, base + random.uniform(-delta, delta))


# ===================== ПУЛ ПОВТОРНОГО ИСПОЛЬЗОВАНИЯ КЛИЕНТА =====================


@dataclass
class _ClientConfig:
    timeout: httpx.Timeout
    follow_redirects: bool
    headers: dict[str, str] | None
    proxies: dict[str, str] | str | None


class _AsyncClientPool:
    """
    Мини-пул: один общий AsyncClient на процесс (для экономии TCP-соединений).
    """

    _client: httpx.AsyncClient | None = None
    _cfg: _ClientConfig | None = None
    _lock = asyncio.Lock()

    @classmethod
    async def get(
        cls,
        *,
        timeout: float | httpx.Timeout = 30.0,
        follow_redirects: bool = False,
        headers: dict[str, str] | None = None,
        profile: str | None = None,
    ) -> httpx.AsyncClient:
        prof = _CFG.get_profile(profile, timeout)
        t = prof.timeout
        proxies = _CFG.proxies

        async with cls._lock:
            # Реиспользуем, если конфиг совпадает
            if (
                cls._client
                and cls._cfg
                and cls._cfg.timeout == t
                and cls._cfg.follow_redirects is follow_redirects
                and (cls._cfg.headers or {}) == (headers or {})
                and cls._cfg.proxies == proxies
            ):
                return cls._client

            if cls._client:
                with suppress(Exception):
                    await cls._client.aclose()

            cls._client = httpx.AsyncClient(
                timeout=t,
                headers=headers,
                follow_redirects=follow_redirects,
                proxies=proxies,
            )
            cls._cfg = _ClientConfig(
                timeout=t, follow_redirects=follow_redirects, headers=headers or {}, proxies=proxies
            )
            return cls._client

    @classmethod
    async def close(cls) -> None:
        async with cls._lock:
            if cls._client:
                with suppress(Exception):
                    await cls._client.aclose()
                cls._client = None
                cls._cfg = None


@asynccontextmanager
async def create_async_client(
    *,
    timeout: float | httpx.Timeout = 30.0,
    follow_redirects: bool = False,
    headers: dict[str, str] | None = None,
    profile: str | None = None,
) -> httpx.AsyncClient:
    """
    Контекстный клиент (если нужна своя «сессия»/заголовки на батч).
    В остальном используйте общий пул через aget/apost.
    """
    prof = _CFG.get_profile(profile, timeout)
    client = httpx.AsyncClient(
        timeout=prof.timeout,
        headers=headers,
        follow_redirects=follow_redirects,
        proxies=_CFG.proxies,
    )
    try:
        yield client
    finally:
        with suppress(Exception):
            await client.aclose()


# ===================== ЕДИНЫЙ ЗАПРОС С РЕТРАЯМИ =====================


async def _arequest_with_retries(
    method: str,
    url: str,
    *,
    timeout: float | httpx.Timeout = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    retries: int = 2,
    backoff: float = 0.5,
    raise_for_status: bool = False,
    follow_redirects: bool = False,
    hard_timeout: float | None = None,
    profile: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """
    Async request: структурные таймауты, Retry-After, джиттер, hard-timeout, общий клиент и глобальный лимитер.
    Параметры по умолчанию совместимы со старым кодом.
    """
    attempt = 0
    prof = _CFG.get_profile(profile, timeout)
    if hard_timeout is None:
        hard_timeout = prof.hard_timeout

    if client is None:
        client = await _AsyncClientPool.get(
            timeout=prof.timeout, follow_redirects=follow_redirects, headers=headers, profile=profile
        )

    while True:
        attempt += 1
        # глобальный лимитер (если включён)
        if _SEMA:
            await _SEMA.acquire()
        try:
            if hard_timeout and hard_timeout > 0:
                async with asyncio.timeout(hard_timeout):  # жёсткий cap на всю операцию
                    resp = await client.request(method, url, params=params, json=json, data=data)
            else:
                resp = await client.request(method, url, params=params, json=json, data=data)

            if _should_retry_response(resp) and attempt <= max(0, retries):
                ra = _retry_after_delay(resp)
                delay = ra if ra is not None else backoff * (2 ** (attempt - 1))
                await asyncio.sleep(_jitter(delay))
                continue

            if raise_for_status:
                resp.raise_for_status()

            observe("http_client.ms", 0, {"method": method, "code": str(resp.status_code)})
            return resp

        except Exception as exc:
            if _is_retryable_exc(exc) and attempt <= max(0, retries):
                await asyncio.sleep(_jitter(backoff * (2 ** (attempt - 1))))
                continue
            inc("http_client_errors_total", method=method)
            raise
        finally:
            if _SEMA:
                with suppress(Exception):
                    _SEMA.release()


def _request_with_retries(
    method: str,
    url: str,
    *,
    timeout: float | httpx.Timeout = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    retries: int = 2,
    backoff: float = 0.5,
    raise_for_status: bool = False,
    follow_redirects: bool = False,
) -> httpx.Response:
    """Sync версия (для совместимости). Рекомендуется использовать async API."""
    timeout_obj = _mk_timeout(timeout)
    attempt = 0

    with httpx.Client(
        timeout=timeout_obj, headers=headers, follow_redirects=follow_redirects, proxies=_CFG.proxies
    ) as client:
        while True:
            attempt += 1
            try:
                resp = client.request(method, url, params=params, json=json, data=data)

                if _should_retry_response(resp) and attempt <= max(0, retries):
                    import time

                    ra = _retry_after_delay(resp)
                    delay = ra if ra is not None else backoff * (2 ** (attempt - 1))
                    time.sleep(_jitter(delay))
                    continue

                if raise_for_status:
                    resp.raise_for_status()
                return resp

            except Exception as exc:
                if _is_retryable_exc(exc) and attempt <= max(0, retries):
                    import time

                    time.sleep(_jitter(backoff * (2 ** (attempt - 1))))
                    continue
                raise


# ===================== ПУБЛИЧНОЕ API (SYNC) =====================


def get(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """Синхронный GET (совместимый)."""
    return _request_with_retries("GET", url, timeout=timeout, headers=headers, params=params)


def post(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Синхронный POST (совместимый)."""
    return _request_with_retries("POST", url, timeout=timeout, headers=headers, json=json, data=data)


# ===================== ПУБЛИЧНОЕ API (ASYNC) =====================


async def aget(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    hard_timeout: float | None = None,
    follow_redirects: bool = False,
    profile: str | None = None,
) -> httpx.Response:
    """Async GET: общий клиент, лимитер, hard-timeout, ретраи, профили таймаутов."""
    return await _arequest_with_retries(
        "GET",
        url,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=int(retries or 2),
        backoff=float(backoff or 0.5),
        follow_redirects=follow_redirects,
        hard_timeout=hard_timeout,
        profile=profile,
    )


async def apost(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    hard_timeout: float | None = None,
    follow_redirects: bool = False,
    profile: str | None = None,
) -> httpx.Response:
    """Async POST: общий клиент, лимитер, hard-timeout, ретраи, профили таймаутов."""
    return await _arequest_with_retries(
        "POST",
        url,
        timeout=timeout,
        headers=headers,
        json=json,
        data=data,
        retries=int(retries or 2),
        backoff=float(backoff or 0.5),
        follow_redirects=follow_redirects,
        hard_timeout=hard_timeout,
        profile=profile,
    )


# ===================== УДОБНЫЕ ХЕЛПЕРЫ =====================


async def aget_json(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    hard_timeout: float | None = None,
    follow_redirects: bool = False,
    profile: str | None = None,
) -> dict[str, Any]:
    resp = await aget(
        url,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=retries,
        backoff=backoff,
        hard_timeout=hard_timeout,
        follow_redirects=follow_redirects,
        profile=profile,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def apost_json(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    hard_timeout: float | None = None,
    follow_redirects: bool = False,
    profile: str | None = None,
) -> dict[str, Any]:
    resp = await apost(
        url,
        json=json,
        data=data,
        timeout=timeout,
        headers=headers,
        retries=retries,
        backoff=backoff,
        hard_timeout=hard_timeout,
        follow_redirects=follow_redirects,
        profile=profile,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def adownload(
    url: str,
    *,
    path: str,
    chunk_size: int = 65536,
    timeout: float = 60.0,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    hard_timeout: float | None = None,
    follow_redirects: bool = True,
    profile: str | None = None,
) -> None:
    """
    Стримовое скачивание в файл (без загрузки всего тела в память).
    """
    client = await _AsyncClientPool.get(
        timeout=timeout, follow_redirects=follow_redirects, headers=headers, profile=profile
    )
    attempt = 0
    while True:
        attempt += 1
        # глобальный лимитер (если включён)
        if _SEMA:
            await _SEMA.acquire()
        try:
            if hard_timeout and hard_timeout > 0:
                async with asyncio.timeout(hard_timeout):
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with open(path, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size):
                                f.write(chunk)
            else:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size):
                            f.write(chunk)
            return
        except Exception as exc:
            if _is_retryable_exc(exc) and attempt <= int(retries or 2):
                await asyncio.sleep(_jitter(float(backoff or 0.5) * (2 ** (attempt - 1))))
                continue
            raise
        finally:
            if _SEMA:
                with suppress(Exception):
                    _SEMA.release()
