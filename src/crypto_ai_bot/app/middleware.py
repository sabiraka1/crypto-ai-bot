# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import time
from typing import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from crypto_ai_bot.utils.rate_limit import MultiLimiter


class RateLimitMiddleware:
    """
    Простейший rate-limit по всем запросам. Использует общий MultiLimiter.
    """
    def __init__(self, app: ASGIApp, *, global_rps: float = 20.0):
        self.app = app
        self.limiter = MultiLimiter(global_rps=global_rps)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            if not self.limiter.try_acquire("global"):
                # 429 Too Many Requests
                async def _send_429(send: Send):
                    await send({
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    })
                    await send({"type": "http.response.body", "body": b"rate limited"})
                await _send_429(send)
                return
        await self.app(scope, receive, send)
