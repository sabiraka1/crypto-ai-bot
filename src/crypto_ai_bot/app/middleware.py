# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# --- request-id wiring (best-effort) ---
try:
    # если в вашем логгере есть контекстный сеттер — используем его
    from crypto_ai_bot.utils.logging import set_request_id  # type: ignore
except Exception:  # pragma: no cover
    set_request_id = None  # type: ignore


# --- rate limit: предпочитаем ваш utils.rate_limit, иначе fallback ---
try:
    from crypto_ai_bot.utils.rate_limit import MultiLimiter, TokenBucket  # type: ignore
except Exception:  # pragma: no cover
    class TokenBucket:  # minimal fallback
        def __init__(self, capacity: int, refill_per_sec: float) -> None:
            self.capacity = float(capacity)
            self.tokens = float(capacity)
            self.refill_per_sec = float(refill_per_sec)
            self._ts = time.monotonic()

        def try_acquire(self, n: float = 1.0) -> bool:
            now = time.monotonic()
            elapsed = now - self._ts
            self._ts = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    class MultiLimiter:
        def __init__(self, **buckets) -> None:
            # buckets: name -> TokenBucket
            self._b = buckets

        def try_acquire(self, name: str, n: float = 1.0) -> bool:
            b = self._b.get(name)
            if not b:
                return True
            return b.try_acquire(n)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Входной rate-limit + Request-ID injection.
    - Глобальный бакет: 'ingress'
    - Пер-IP бакет: 'ip:<addr>'
    Параметры берём из settings, если переданы в конструктор.
    """

    def __init__(
        self,
        app,
        *,
        global_rps: int = 20,
        ip_rps: int = 10,
        burst_multiplier: float = 2.0,
        settings: Optional[object] = None,
    ) -> None:
        super().__init__(app)

        # можно прокинуть через settings.* если есть
        if settings is not None:
            global_rps = int(getattr(settings, "INGRESS_GLOBAL_RPS", global_rps))
            ip_rps = int(getattr(settings, "INGRESS_IP_RPS", ip_rps))
            burst_multiplier = float(getattr(settings, "INGRESS_BURST_MULT", burst_multiplier))

        self.global_bucket = TokenBucket(
            capacity=int(global_rps * burst_multiplier),
            refill_per_sec=float(global_rps),
        )
        self.ip_buckets: dict[str, TokenBucket] = {}
        self.limiter = MultiLimiter(ingress=self.global_bucket)

    async def dispatch(self, request: Request, call_next) -> Response:
        # --- request id ---
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        if set_request_id:
            try:
                set_request_id(req_id)  # добавить в контекст логгера, если поддерживается
            except Exception:
                pass

        # --- rate-limit global ---
        if not self.limiter.try_acquire("ingress"):
            return JSONResponse({"detail": "rate limit exceeded (global)"}, status_code=429, headers={"X-Request-ID": req_id})

        # --- rate-limit per-IP ---
        client_ip = (request.client.host if request.client else "unknown") or "unknown"
        bucket = self.ip_buckets.get(client_ip)
        if bucket is None:
            # по умолчанию: половина глобального
            per_ip_rps = max(int(self.global_bucket.refill_per_sec // 2), 1)
            bucket = self.ip_buckets[client_ip] = TokenBucket(
                capacity=int(per_ip_rps * 2),
                refill_per_sec=float(per_ip_rps),
            )

        if not bucket.try_acquire(1.0):
            return JSONResponse({"detail": "rate limit exceeded (ip)"}, status_code=429, headers={"X-Request-ID": req_id})

        # --- продолжить обработку ---
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = req_id
        return resp
