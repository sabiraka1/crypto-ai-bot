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
    HTTP middleware:
    - ставит request_id (X-Request-Id или генерит UUID4)
    - correlation_id = X-Correlation-Id, иначе совпадает с request_id
    - снимает http_* метрики
    """
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    cid = request.headers.get("x-correlation-id") or rid  # ← важное изменение

    set_request_id(rid)
    set_correlation_id(cid)

    t0 = time.time()
    code = "500"
    response: Response
    try:
        response = await call_next(request)
        code = str(response.status_code)
    finally:
        dt = max(0.0, time.time() - t0)
        metrics.inc("http_requests_total", {"method": request.method.upper(), "path": request.url.path, "code": code})
        metrics.observe_histogram("http_request_duration_seconds", dt, {"method": request.method.upper(), "path": request.url.path})
    try:
        response.headers["X-Request-Id"] = rid  # type: ignore
        response.headers["X-Correlation-Id"] = cid  # type: ignore
    except Exception:
        pass
    return response


def register_middlewares(app: ASGIApp) -> None:
    from fastapi import FastAPI
    fast: FastAPI = app  # type: ignore
    fast.middleware("http")(http_metrics_and_ids)
