from __future__ import annotations
import uuid
import contextvars
from typing import Callable
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# контекстный correlation-id, доступен из любого места
_correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

def get_correlation_id() -> str:
    return _correlation_id_ctx.get()

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        # берём из входящих заголовков или генерим
        incoming = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        cid = incoming or str(uuid.uuid4())
        token = _correlation_id_ctx.set(cid)
        try:
            response = await call_next(request)
        finally:
            _correlation_id_ctx.reset(token)
        response.headers["X-Request-ID"] = cid
        return response

def register_middlewares(app):
    app.add_middleware(CorrelationIdMiddleware)
