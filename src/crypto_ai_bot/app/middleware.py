# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable, Awaitable

from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse


class _TokenBucket:
    """
    Простой процессный token-bucket:
      - rps: пополнение токенов в секунду
      - burst: максимальное число токенов (всплеск)
    Потокобезопасен для asyncio.
    """
    def __init__(self, rps: float, burst: int) -> None:
        self._rps = float(max(0.1, rps))
        self._burst = int(max(1, burst))
        self._tokens = float(self._burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            dt = now - self._last
            if dt > 0:
                self._tokens = min(self._burst, self._tokens + dt * self._rps)
                self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class RateLimitMiddleware:
    """
    ASGI middleware:
      - добавляет X-Request-ID в ответ
      - ограничивает входной RPS простым token-bucket'ом
    Параметры:
      rps: средний запросов в секунду (default 5)
      burst: максимальный всплеск (default 10)
    """
    def __init__(self, app: ASGIApp, *, rps: int = 5, burst: int = 10) -> None:
        self.app = app
        self.bucket = _TokenBucket(rps=float(rps), burst=int(burst))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # request id
        req_id = uuid.uuid4().hex
        # пробуем сохранить для доступа в request.state.request_id
        state = scope.setdefault("state", {})
        try:
            state["request_id"] = req_id
        except Exception:
            pass

        if not await self.bucket.acquire():
            # 429 ответ с заголовком X-Request-ID
            resp = JSONResponse({"ok": False, "error": "rate_limited", "request_id": req_id}, status_code=429)
            async def _send(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", [])) + [(b"x-request-id", req_id.encode("utf-8"))]
                    message = {**message, "headers": headers}
                await send(message)
            await resp(scope, receive, _send)
            return

        # оборачиваем send, чтобы проставить X-Request-ID в успешный ответ
        async def send_with_reqid(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", [])) + [(b"x-request-id", req_id.encode("utf-8"))]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_reqid)
