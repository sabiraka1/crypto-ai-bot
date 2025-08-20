# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.core.orchestrator import Orchestrator

# Если у вас есть middleware с request_id/rate-limit — подключите его здесь
# from crypto_ai_bot.app.middleware import RequestIDMiddleware, RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Сборка контейнера
    container: Container = build_container()
    app.state.container = container

    # Старт EventBus
    await container.bus.start()

    # Старт Оркестратора
    orchestrator = Orchestrator(container)
    app.state.orchestrator = orchestrator
    await orchestrator.start()

    try:
        yield
    finally:
        # Остановка оркестратора
        try:
            await orchestrator.stop()
        except Exception:
            pass
        # Остановка шины событий
        try:
            await container.bus.stop()
        except Exception:
            pass
        # Закрытие соединения с БД
        try:
            container.con.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)

# Подключение middleware (если используются)
# app.add_middleware(RequestIDMiddleware)
# app.add_middleware(RateLimitMiddleware)


@app.get("/health")
async def health():
    c: Container = app.state.container
    # Базовый health; дополняйте проверками брокера/БД/очередей
    return {
        "ok": True,
        "mode": getattr(c.settings, "MODE", "paper"),
        "bus_queue": getattr(c.bus, "qsize", lambda: None)(),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    """
    Простой вебхук: сверяем секрет и передаём payload адаптеру.
    """
    c: Container = app.state.container
    secret_expected = getattr(c.settings, "TELEGRAM_BOT_SECRET", None)
    secret_got = req.query_params.get("secret")
    if secret_expected and secret_got != secret_expected:
        raise HTTPException(status_code=401, detail="invalid secret")

    try:
        payload: Any = await req.json()
    except Exception:
        payload = {}

    # Импорт локально, чтобы не тянуть адаптер при старте, если он не нужен
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update

    try:
        await tg_handle_update(c, payload)
    except Exception as e:
        # не валим вебхук 500-кой, логика адаптера сама логирует ошибки
        return JSONResponse(status_code=200, content={"ok": False, "error": str(e)})

    return {"ok": True}


# Опционально: корневой роут
@app.get("/")
async def root():
    return {"name": "crypto-ai-bot", "status": "running"}
