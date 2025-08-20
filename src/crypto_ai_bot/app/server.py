# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.core.orchestrator import Orchestrator

# опциональные вещи — если нет, просто не будем подключать
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update
except Exception:  # pragma: no cover
    telegram_handle_update = None  # type: ignore

try:
    from crypto_ai_bot.app.middleware import RateLimitMiddleware  # наш тонкий ASGI RL + request_id
except Exception:  # pragma: no cover
    RateLimitMiddleware = None  # type: ignore

try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # стандартный /metrics
except Exception:  # pragma: no cover
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="crypto-ai-bot", version="1.0")

    # Settings/Container на процесс
    settings = Settings.load()
    container = build_container(settings)
    app.state.settings = settings
    app.state.container = container
    app.state.orchestrator = None

    # Входной rate-limit + request_id (если модуль есть)
    if RateLimitMiddleware:
        app.add_middleware(RateLimitMiddleware,
                           requests_per_sec=getattr(settings, "HTTP_RPS_LIMIT", 50))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        c: Container = app.state.container

        # Запускаем шину событий и оркестратор
        await c.bus.start()
        orch = Orchestrator(container=c)
        await orch.start()
        app.state.orchestrator = orch

        try:
            yield
        finally:
            # shutdown
            try:
                if app.state.orchestrator:
                    await app.state.orchestrator.stop()
            finally:
                await c.bus.stop()

    app.router.lifespan_context = lifespan

    # ---------- ROUTES ----------

    @app.get("/", response_model=dict)
    async def root():
        s: Settings = app.state.settings
        return {"ok": True, "mode": s.MODE, "exchange": s.EXCHANGE, "symbol": s.SYMBOL}

    @app.get("/health", response_model=dict)
    async def health():
        """
        Базовый health — не блокирующий и без тяжёлых операций.
        """
        c: Container = app.state.container
        ok_db = True
        ok_bus = c.bus.is_running()
        ok_broker = True

        # очень лёгкие проверки (без сетевых блокировок)
        try:
            c.trades_repo.ensure_ready()
        except Exception:  # pragma: no cover
            ok_db = False

        return {
            "ok": bool(ok_db and ok_bus and ok_broker),
            "db": ok_db,
            "bus": ok_bus,
            "broker": ok_broker,
        }

    @app.get("/metrics")
    async def metrics():
        """
        Экспорт prom-метрик, если установлен prometheus_client.
        """
        if not generate_latest:  # pragma: no cover
            return PlainTextResponse("metrics unavailable", status_code=503)
        data = generate_latest()  # type: ignore
        return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        """
        Минимально безопасный вебхук: проверяем секрет и передаём payload адаптеру.
        """
        s: Settings = app.state.settings
        secret_query = request.query_params.get("secret")
        secret_header = request.headers.get("X-Telegram-Secret-Token")
        expected = getattr(s, "TELEGRAM_BOT_SECRET", None)

        if not expected:
            raise HTTPException(status_code=403, detail="telegram secret is not configured")

        if secret_query != expected and secret_header != expected:
            raise HTTPException(status_code=403, detail="invalid telegram secret")

        if telegram_handle_update is None:  # pragma: no cover
            raise HTTPException(status_code=501, detail="telegram adapter not available")

        try:
            payload: Dict[str, Any] = await request.json()
        except Exception:
            payload = {}

        await telegram_handle_update(app.state.container, payload)
        return JSONResponse({"ok": True})

    return app


# Uvicorn entrypoint
app = create_app()
