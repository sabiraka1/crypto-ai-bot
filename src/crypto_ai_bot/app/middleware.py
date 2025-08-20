# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import time
import uuid
from typing import Callable, Awaitable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

try:
    # наш общий лимитер из utils.rate_limit (если нет MultiLimiter — используем TokenBucket локально)
    from crypto_ai_bot.utils.rate_limit import MultiLimiter
except Exception:  # fallback, чтобы не падать
    MultiLimiter = None  # type: ignore[assignment]

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

def get_request_id() -> str:
    return _request_id_ctx.get()

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Входной rate-limit для HTTP (ASGI). Ограничивает RPS на весь сервер.
    Никаких внешних зависимостей: используем MultiLimiter, если он есть.
    Параллельно расставляет X-Request-ID в ответ и в контекст (для логгера).
    """
    def __init__(self, app, *, global_rps: int = 10) -> None:
        super().__init__(app)
        self.global_rps = max(1, global_rps)

        if MultiLimiter is not None:
            # один общий бакет для входящих HTTP-запросов
            self.limiter = MultiLimiter(global_rps=self.global_rps)
        else:
            # простой внутренний бакет на случай отсутствия utils.rate_limit
            self._last = time.monotonic()
            self._tokens = self.global_rps
            self._capacity = self.global_rps

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # request_id
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = _request_id_ctx.set(rid)
        try:
            # rate-limit
            if MultiLimiter is not None:
                if not self.limiter.try_acquire("http", 1):
                    # мягкий возврат 429
                    return Response(status_code=429, content="Too Many Requests")
            else:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._capacity)
                if self._tokens < 1:
                    return Response(status_code=429, content="Too Many Requests")
                self._tokens -= 1

            resp = await call_next(request)
            resp.headers["X-Request-ID"] = rid
            return resp
        finally:
            _request_id_ctx.reset(token)
