from __future__ import annotations
import time
from typing import Dict, Tuple, Optional, Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from crypto_ai_bot.utils.metrics import inc, gauge
from crypto_ai_bot.utils.logging import REQUEST_ID, new_request_id, get_logger, mask_dict

_log = get_logger("http")

# ---------------------- Request ID ----------------------

class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Генерирует/прокидывает X-Request-ID и сохраняет его в contextvars для логов.
    """
    def __init__(self, app, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get(self.header_name) or new_request_id()
        token = REQUEST_ID.set(req_id)
        try:
            response = await call_next(request)
            response.headers[self.header_name] = req_id
            return response
        finally:
            REQUEST_ID.reset(token)

# ---------------------- Rate limit ----------------------

class _TokenBucket:
    __slots__ = ("rate", "burst", "tokens", "ts")

    def __init__(self, rate: float, burst: float):
        self.rate = float(max(0.1, rate))
        self.burst = float(max(1.0, burst))
        self.tokens = self.burst
        self.ts = time.time()

    def allow(self) -> bool:
        now = time.time()
        self.tokens = min(self.burst, self.tokens + (now - self.ts) * self.rate)
        self.ts = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Пер-IP пер-путь токен-бакеты.
    """
    def __init__(self, app, *,
                 default_rps: float = 5.0,
                 default_burst: float = 10.0,
                 overrides: Optional[Dict[str, Tuple[float, float]]] = None):
        super().__init__(app)
        self.default_rps = float(default_rps)
        self.default_burst = float(default_burst)
        self.overrides = overrides or {}
        self._buckets: Dict[Tuple[str, str], _TokenBucket] = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = (request.client.host if request.client else "unknown")
        path = request.url.path

        rps, burst = self.overrides.get(path, (self.default_rps, self.default_burst))
        key = (client_ip, path)
        b = self._buckets.get(key)
        if b is None:
            b = _TokenBucket(rps, burst)
            self._buckets[key] = b

        if not b.allow():
            inc("http_429", {"path": path, "method": request.method})
            return JSONResponse({"detail": "rate limited"}, status_code=429)

        return await call_next(request)

# ---------------------- Body size limit ----------------------

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Ограничение размера тела запроса (пер-путь опционально).
    """
    def __init__(self, app, *, default_limit_bytes: int = 256_000,
                 overrides: Optional[Dict[str, int]] = None):
        super().__init__(app)
        self.default_limit = int(max(1_024, default_limit_bytes))
        self.overrides = overrides or {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        limit = int(self.overrides.get(path, self.default_limit))

        body = await request.body()
        if len(body) > limit:
            inc("http_413", {"path": path, "method": request.method})
            return JSONResponse({"detail": "payload too large"}, status_code=413)

        # прокинем уже считанное тело дальше
        async def receive_gen():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive_gen  # type: ignore[attr-defined]
        return await call_next(request)

# ---------------------- Request logging + metrics ----------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Логирует начало/окончание запроса, пишет метрики.
    """
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        path = request.url.path
        method = request.method
        ip = request.client.host if request.client else "unknown"

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as e:
            status = 500
            inc("http_5xx", {"path": path, "method": method})
            _log.error("request_error", extra={"extra": mask_dict({"path": path, "method": method, "ip": ip, "error": repr(e)})})
            raise
        finally:
            dur = time.perf_counter() - start
            inc("http_requests_total", {"path": path, "method": method, "status": str(status)})
            gauge("http_request_duration_seconds", dur, {"path": path, "method": method})
            _log.info("request",
                      extra={"extra": mask_dict({"path": path, "method": method, "status": status, "ip": ip, "duration_ms": round(dur*1000, 2)})})
        return response

# ---------------------- registration helper ----------------------

def register_middlewares(app, settings) -> None:
    """
    Подключение мидлварей с конфигом из Settings.
    Порядок важен: RequestId -> BodyLimit -> RateLimit -> Logging
    """
    # Request ID — всегда первым
    app.add_middleware(RequestIdMiddleware)

    # Body limit
    default_limit = int(getattr(settings, "HTTP_BODY_LIMIT_DEFAULT", 256_000))
    bl_over = {
        "/telegram": int(getattr(settings, "HTTP_BODY_LIMIT_TELEGRAM", 64_000)),
    }
    app.add_middleware(BodySizeLimitMiddleware,
                       default_limit_bytes=default_limit,
                       overrides=bl_over)

    # Rate limit
    default_rps = float(getattr(settings, "HTTP_RPS_DEFAULT", 5.0))
    default_burst = float(getattr(settings, "HTTP_BURST_DEFAULT", 10.0))
    rl_over = {
        "/telegram": (float(getattr(settings, "HTTP_RPS_TELEGRAM", 1.5)),
                      float(getattr(settings, "HTTP_BURST_TELEGRAM", 5.0))),
        "/metrics":  (float(getattr(settings, "HTTP_RPS_METRICS", 1.0)),
                      float(getattr(settings, "HTTP_BURST_METRICS", 2.0))),
    }
    app.add_middleware(RateLimitMiddleware,
                       default_rps=default_rps,
                       default_burst=default_burst,
                       overrides=rl_over)

    # Request logging + metrics — последним
    app.add_middleware(RequestLoggingMiddleware)
