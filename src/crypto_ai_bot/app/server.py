# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.middleware import RateLimitMiddleware
from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Жизненный цикл приложения:
    - собираем DI-контейнер
    - стартуем Orchestrator
    - на shutdown — останавливаем таски аккуратно (graceful)
    """
    settings = Settings.load()
    container = build_container(settings=settings)
    app.state.container = container

    # Запуск оркестратора
    try:
        await container.orchestrator.start()
        logger.info("Orchestrator started")
    except Exception:
        logger.exception("Failed to start orchestrator")
        raise

    try:
        yield
    finally:
        try:
            await container.orchestrator.stop()
            logger.info("Orchestrator stopped")
        except Exception:
            logger.exception("Failed to stop orchestrator")


app = FastAPI(lifespan=lifespan)

# Входной rate-limit и request_id
app.add_middleware(RateLimitMiddleware)


@app.get("/")
async def root() -> Dict[str, Any]:
    c = app.state.container
    s = c.settings
    return {
        "name": "crypto-ai-bot",
        "mode": s.MODE,
        "symbol": s.SYMBOL,
        "exchange": s.EXCHANGE,
        "running": True,
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    c = app.state.container
    ok_db = True
    ok_bus = True
    ok_orch = True
    try:
        # Лёгкий «пульс» БД: PRAGMA user_version
        _ = c.sqlite.execute("PRAGMA user_version").fetchone()
    except Exception:
        ok_db = False
    try:
        ok_bus = c.bus is not None
    except Exception:
        ok_bus = False
    try:
        ok_orch = c.orchestrator is not None
    except Exception:
        ok_orch = False

    status_overall = ok_db and ok_bus and ok_orch
    return {
        "status": "ok" if status_overall else "degraded",
        "db": ok_db,
        "bus": ok_bus,
        "orchestrator": ok_orch,
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    """
    Идемпотентный Telegram webhook:
    - сверяем секрет (X-Telegram-Secret-Token или ?secret=)
    - безопасно парсим JSON
    - вызываем handle_update(container, payload)
    """
    c = app.state.container
    secret_cfg = c.settings.TELEGRAM_BOT_SECRET.strip()
    # Секрет может прийти в заголовке Telegram либо как query
    secret_in = request.headers.get("X-Telegram-Secret-Token") or request.query_params.get("secret") or ""

    if secret_cfg and secret_in != secret_cfg:
        return Response(
            content=json.dumps({"ok": False, "error": "forbidden"}),
            status_code=status.HTTP_403_FORBIDDEN,
            media_type="application/json",
        )

    try:
        body = await request.body()
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        logger.exception("telegram_webhook: bad json")
        return Response(
            content=json.dumps({"ok": False, "error": "bad_json"}),
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="application/json",
        )

    try:
        await telegram_handle_update(c, payload)
        return Response(content=json.dumps({"ok": True}), media_type="application/json")
    except Exception:
        logger.exception("telegram_webhook: handler failed")
        return Response(
            content=json.dumps({"ok": False, "error": "handler_error"}),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json",
        )
