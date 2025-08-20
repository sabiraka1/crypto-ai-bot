# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import uuid
from typing import Callable, Awaitable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.rate_limit import TokenBucket


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Глобальный входной rate-limit на процесс (ASGI-уровень)."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        cap = int(getattr(settings, "HTTP_RL_CAPACITY", 60))
        window = float(getattr(settings, "HTTP_RL_WINDOW_SEC", 1.0))
        refill = cap / max(0.001, window)
        self.bucket = TokenBucket(capacity=cap, refill_per_sec=refill)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # request_id для корреляции логов
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id

        if not self.bucket.try_acquire(1.0):
            # 429 Too Many Requests
            return Response(status_code=429, content="rate limited")

        resp = await call_next(request)
        resp.headers["X-Request-ID"] = req_id
        return resp
