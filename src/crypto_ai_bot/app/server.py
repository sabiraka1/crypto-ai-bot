"""
FastAPI сервер приложения:
— Lifespan: старт/стоп AsyncEventBus и Orchestrator (graceful)
— /health, /ready, /metrics, /telegram/webhook
— Готов к запуску через gunicorn: gunicorn -k uvicorn.workers.UvicornWorker crypto_ai_bot.app.server:app
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

# DI-контейнер
from crypto_ai_bot.app.compose import build_container  # ожидается в репозитории
# Telegram адаптер
from crypto_ai_bot.app.adapters.telegram import handle_update
# Orchestrator
from crypto_ai_bot.core.orchestrator import Orchestrator


def _safe(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Сборка контейнера
    container = build_container()
    app.state.container = container

    # Старт EventBus
    if hasattr(container, "bus") and hasattr(container.bus, "start"):
        await container.bus.start()

    # Старт Orchestrator
    app.state.orchestrator = Orchestrator(
        settings=container.settings,
        broker=container.broker,
        trades_repo=container.trades_repo,
        positions_repo=container.positions_repo,
        exits_repo=getattr(container, "exits_repo", None),
        idempotency_repo=getattr(container, "idempotency_repo", None),
        bus=container.bus,
        limiter=getattr(container, "limiter", None),
    )
    await app.state.orchestrator.start()

    try:
        yield
    finally:
        # Graceful stop orchestrator
        try:
            if getattr(app.state, "orchestrator", None):
                await app.state.orchestrator.stop()
        except Exception:
            pass
        # Stop EventBus
        try:
            if hasattr(container, "bus") and hasattr(container.bus, "stop"):
                await container.bus.stop()
        except Exception:
            pass


def create_app() -> FastAPI:
    application = FastAPI(title="crypto-ai-bot", version="1.0", lifespan=lifespan)

    @application.get("/", tags=["meta"])
    async def root():
        return {"ok": True, "name": "crypto-ai-bot"}

    @application.get("/ready", tags=["meta"])
    async def ready():
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {"running": True}
        ok = bool(bus_h.get("running"))
        return JSONResponse({"ready": ok, "bus": bus_h}, status_code=200 if ok else 503)

    @application.get("/health", tags=["meta"])
    async def health():
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {"running": True}
        details: Dict[str, Any] = {
            "mode": getattr(c.settings, "MODE", "paper"),
            "symbol": getattr(c.settings, "SYMBOL", "BTC/USDT"),
            "timeframe": getattr(c.settings, "TIMEFRAME", "1h"),
            "bus": bus_h,
            "pending_orders": _safe(c.trades_repo, "count_pending", lambda: 0)(),
        }
        return JSONResponse({"ok": True, "details": details})

    @application.get("/metrics", tags=["meta"])
    async def metrics():
        # Лёгкая интеграция: utils.metrics.export() если есть
        try:
            from crypto_ai_bot.utils import metrics as m  # type: ignore
            if hasattr(m, "export"):
                return PlainTextResponse(m.export())
        except Exception:
            pass
        # Фолбэк: несколько ключевых метрик из bus.health
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {}
        text = []
        for k, v in bus_h.items():
            text.append(f"app_bus_{k} {v}")
        return PlainTextResponse("\n".join(text) + "\n")

    @application.post("/telegram/webhook", tags=["adapters"])
    async def telegram_webhook(request: Request):
        body = await request.body()
        c = application.state.container
        return await handle_update(application, body, c)

    return application


app = create_app()
