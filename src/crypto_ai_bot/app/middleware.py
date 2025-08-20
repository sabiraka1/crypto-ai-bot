# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import uuid
from typing import Callable, Awaitable
from starlette.types import ASGIApp, Receive, Scope, Send

from crypto_ai_bot.utils.rate_limit import MultiLimiter, TokenBucket


class RateLimitMiddleware:
    """
    Очень лёгкий входной лимитер для HTTP (ASGI).
    Не душим /metrics и /health.
    """
    def __init__(self, app: ASGIApp, *, rps: int = 20):
        self.app = app
        # глобальный http-бакет — можно вынести в настройки
        self.limiter = MultiLimiter({"http": TokenBucket(rps, 1.0)})

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/metrics") or path.startswith("/health"):
            await self.app(scope, receive, send)
            return

        if not self.limiter.try_acquire("http", 1.0):
            await self._too_many(scope, send)
            return

        # request id в заголовок ответа — удобно для трассировки
        req_id = str(uuid.uuid4())
        async def send_with_req_id(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", req_id.encode()))
            await send(message)

        await self.app(scope, receive, send_with_req_id)

    async def _too_many(self, scope: Scope, send: Send):
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": b"Too Many Requests"})
