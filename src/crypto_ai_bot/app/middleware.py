# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import json
import time
import uuid
from typing import Callable, Awaitable

from starlette.types import ASGIApp, Receive, Scope, Send, Message

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.rate_limit import MultiLimiter


class RateLimitMiddleware:
    """
    Входной rate-limit для HTTP (ASGI). Единый источник истины — utils.rate_limit.MultiLimiter.
    Также добавляет X-Request-ID в ответ и прокидывает request_id в логи через контекст.
    """

    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        self.app = app
        self.settings = settings or Settings.load()
        # Один глобальный бакет для HTTP. Если нужно — можно добавить по-роутовый ключ
        http_rps = int(getattr(self.settings, "HTTP_RPS", 20))
        self.limiter = MultiLimiter(global_rps=http_rps)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        start_ts = time.time()

        # Берём токен из единого лимитера
        if not self.limiter.try_acquire("http", 1):
            body = json.dumps({"error": "rate_limited"}).encode("utf-8")

            async def _send(msg: Message) -> None:
                if msg["type"] == "http.response.start":
                    headers = [(b"content-type", b"application/json"),
                               (b"x-request-id", request_id.encode("utf-8"))]
                    msg = {**msg, "status": 429, "headers": headers}
                elif msg["type"] == "http.response.body":
                    msg = {**msg, "body": body}
                await send(msg)

            await _send({"type": "http.response.start"})
            await _send({"type": "http.response.body"})
            return

        # Оборачиваем send, чтобы добавить X-Request-Id
        async def send_with_header(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                headers = msg.get("headers") or []
                headers = list(headers) + [(b"x-request-id", request_id.encode("utf-8"))]
                msg = {**msg, "headers": headers}
            await send(msg)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            # здесь можно наблюдать latency через utils.metrics, если нужно
            _ = time.time() - start_ts
