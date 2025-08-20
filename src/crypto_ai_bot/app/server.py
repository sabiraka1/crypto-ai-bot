# src/crypto_ai_bot/app/server.py
"""
FastAPI-приложение:
- /health — базовый health
- /metrics — Prometheus
- Telegram webhook (если включен)
- lifespan: сборка контейнера, запуск/останов оркестратора
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import PlainTextResponse, JSONResponse

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.utils.logging import get_logger  # предполагаемый утиль логгера


app = FastAPI(title="crypto-ai-bot")
log = get_logger("app")

# Контейнер «один на процесс»
_container: Optional[Any] = None


@app.on_event("startup")
async def _startup() -> None:
    global _container
    _container = build_container()
    # Запуск event-bus — если требуется вне оркестратора
    if getattr(_container, "event_bus", None) and hasattr(_container.event_bus, "start"):
        # event_bus.start() может быть sync/async — поддержим оба.
        try:
            maybe = _container.event_bus.start()
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            log.exception("event_bus.start failed")

    if getattr(_container, "orchestrator", None):
        await _container.orchestrator.start()
    log.info("startup complete")


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _container
    try:
        if getattr(_container, "orchestrator", None):
            await _container.orchestrator.stop()
        if getattr(_container, "event_bus", None) and hasattr(_container.event_bus, "stop"):
            try:
                maybe = _container.event_bus.stop()
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                log.exception("event_bus.stop failed")
    finally:
        _container = None
    log.info("shutdown complete")


@app.get("/health")
async def health() -> JSONResponse:
    c = _container
    broker_ok = bool(getattr(c, "broker", None))
    db_ok = bool(getattr(c, "db", None))
    bus_ok = bool(getattr(c, "event_bus", None))
    # heartbeat из KV
    hb = None
    kv = getattr(getattr(c, "repositories", c), "kv_repo", None)
    if kv and hasattr(kv, "get_with_timestamp"):
        try:
            hb = kv.get_with_timestamp("orchestrator_heartbeat_ms")
        except Exception:
            hb = None
    return JSONResponse(
        {
            "ok": broker_ok and db_ok,
            "components": {
                "broker": broker_ok,
                "db": db_ok,
                "bus": bus_ok,
                "heartbeat": {"value": hb[0], "updated_ms": hb[1]} if hb else None,
            },
        }
    )


@app.get("/metrics")
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# --- Telegram webhook (если используете) ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    c = _container
    if c is None:
        return JSONResponse({"error": "not_ready"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    secret_expected = getattr(c.settings, "TELEGRAM_BOT_SECRET", None)
    secret = request.query_params.get("secret")
    if secret_expected and secret != secret_expected:
        return JSONResponse({"error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)

    payload = await request.json()
    handler = getattr(c, "telegram_handler", None) or getattr(c, "telegram", None)
    if handler is None:
        return JSONResponse({"ok": True, "note": "telegram handler disabled"})
    try:
        # единая сигнатура: handle_update(container, payload)
        maybe = handler.handle_update(c, payload)
        if asyncio.iscoroutine(maybe):
            await maybe
        return JSONResponse({"ok": True})
    except Exception as e:
        log.exception("telegram_webhook failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
