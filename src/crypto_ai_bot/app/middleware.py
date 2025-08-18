# src/crypto_ai_bot/app/middleware.py
from __future__ import annotations

import time
import uuid
from typing import Callable, Awaitable
from fastapi import Request, Response
from starlette.types import ASGIApp

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import set_request_id, set_correlation_id


async def http_metrics_and_ids(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Простой HTTP middleware:
    - проставляет request_id (из заголовка X-Request-Id или генерирует UUID4)
    - пробрасывает correlation_id (если передан X-Correlation-Id)
    - снимает http_request_total и http_request_duration_seconds
    """
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    cid = request.headers.get("x-correlation-id") or None

    set_request_id(rid)
    if cid:
        set_correlation_id(cid)

    t0 = time.time()
    code = "500"
    try:
        response = await call_next(request)
        code = str(response.status_code)
        return response
    finally:
        dt = max(0.0, time.time() - t0)
        metrics.inc("http_requests_total", {"method": request.method.upper(), "path": request.url.path, "code": code})
        metrics.observe_histogram("http_request_duration_seconds", dt, {"method": request.method.upper(), "path": request.url.path})
        # возвращаем request-id клиенту для трассировки
        try:
            response.headers["X-Request-Id"] = rid  # type: ignore
            if cid:
                response.headers["X-Correlation-Id"] = cid  # type: ignore
        except Exception:
            pass


def register_middlewares(app: ASGIApp) -> None:
    from fastapi import FastAPI  # типизация для девов
    fast: FastAPI = app  # type: ignore
    fast.middleware("http")(http_metrics_and_ids)
