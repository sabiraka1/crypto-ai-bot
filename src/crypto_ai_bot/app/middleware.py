from __future__ import annotations
import time
from typing import Dict, Tuple, Optional, Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from crypto_ai_bot.utils.metrics import inc


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
    Пер-IP пер-путь токен-бакеты. Настройки:
      default_rps / default_burst — по умолчанию
      overrides: { "/telegram": (1.5, 5), "/metrics": (1.0, 2) } и т.п.
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
            inc("http_429", {"path": path})
            return JSONResponse({"detail": "rate limited"}, status_code=429)

        return await call_next(request)


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
            inc("http_413", {"path": path})
            return JSONResponse({"detail": "payload too large"}, status_code=413)

        # прокинем уже считанное тело дальше
        async def receive_gen():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive_gen  # type: ignore[attr-defined]
        return await call_next(request)


def register_middlewares(app, settings) -> None:
    """
    Подключение мидлварей с конфигом из Settings.
    """
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

    # Body limit
    default_limit = int(getattr(settings, "HTTP_BODY_LIMIT_DEFAULT", 256_000))
    bl_over = {
        "/telegram": int(getattr(settings, "HTTP_BODY_LIMIT_TELEGRAM", 64_000)),
    }
    app.add_middleware(BodySizeLimitMiddleware,
                       default_limit_bytes=default_limit,
                       overrides=bl_over)
