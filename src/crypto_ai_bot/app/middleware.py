# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from crypto_ai_bot.utils.rate_limit import MultiLimiter
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # attach to scope for loggers that read it
        request.state.request_id = req_id
        resp: Response = await call_next(request)
        resp.headers["X-Request-ID"] = req_id
        return resp

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple ingress rate-limit using shared MultiLimiter (per-instance).
    """
    def __init__(self, app, limiter: MultiLimiter, bucket_name: str = "ingress"):
        super().__init__(app)
        self._limiter = limiter
        self._bucket = bucket_name

    async def dispatch(self, request: Request, call_next):
        if not self._limiter.try_acquire(self._bucket, 1):
            return Response("Too Many Requests", status_code=429)
        return await call_next(request)
