# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations
import uuid
from typing import Callable, Awaitable
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.base import BaseHTTPMiddleware
from crypto_ai_bot.utils.rate_limit import MultiLimiter

class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str = "x-request-id") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request, call_next):
        req_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers[self.header_name] = req_id
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Простой RPS-лимит на входящие HTTP запросы, использует общий MultiLimiter.
    Передайте готовый limiter из compose/server: buckets={"inbound_http": TokenBucket(...)}.
    """
    def __init__(self, app: ASGIApp, limiter: MultiLimiter, bucket_name: str = "inbound_http") -> None:
        super().__init__(app)
        self.limiter = limiter
        self.bucket_name = bucket_name

    async def dispatch(self, request, call_next):
        # можно пропускать health/metrics, если нужно
        path = request.url.path
        if not self.limiter.try_acquire(self.bucket_name, 1.0):
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("rate limited", status_code=429)
        return await call_next(request)
