# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.middleware import RateLimitMiddleware
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.utils.logging import get_logger

# Telegram adapter (унифицированная сигнатура)
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update
except Exception:  # pragma: no cover
    telegram_handle_update = None  # type: ignore

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Собираем контейнер и всё окружение
    c = build_container()
    app.state.container = c

    # Запуск шины и оркестратора: строго await
    await c.bus.start()
    await c.orchestrator.start()
    logger.info("application started: mode=%s exchange=%s db=%s", c.settings.MODE, c.settings.EXCHANGE, c.settings.DB_PATH)

    try:
        yield
    finally:
        # Корректное завершение: сначала оркестратор, затем шина
        try:
            await c.orchestrator.stop()
        except Exception as e:  # pragma: no cover
            logger.exception("orchestrator.stop failed: %s", e)

        try:
            await c.bus.stop()
        except Exception as e:  # pragma: no cover
            logger.exception("bus.stop failed: %s", e)

        # Закрыть БД-подключение (если есть .close)
        try:
            if hasattr(c.db, "close"):
                c.db.close()
        except Exception as e:  # pragma: no cover
            logger.warning("db.close failed: %s", e)

        logger.info("application stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="crypto-ai-bot", lifespan=lifespan)

    # Подключаем входной rate-limit + request-id middleware
    # Параметры берём из settings, чтобы не дублировать конфиг
    @app.middleware("http")
    async def _attach_container_to_request(request: Request, call_next):
        # небольшой трюк, чтобы мидлварь могла читать settings
        request.state.container = getattr(app.state, "container", None)
        return await call_next(request)

    app.add_middleware(
        RateLimitMiddleware,
        settings=lambda: getattr(app.state, "container", None) and app.state.container.settings,  # lazy, но совместимо
    )

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        c = app.state.container
        ok = True
        details = {
            "mode": c.settings.MODE,
            "exchange": c.settings.EXCHANGE,
            "symbol": c.settings.SYMBOL,
            "db_path": c.settings.DB_PATH,
            "bus": {"queue_size": c.bus.qsize(), "concurrency": c.bus.concurrency},
            "orchestrator": {"running": c.orchestrator.is_running()},
        }
        return {"ok": ok, "details": details}

    @app.get("/metrics")
    async def metrics() -> Response:
        # лёгкая интеграция с utils.metrics; если нет — возвращаем заглушку
        try:
            from crypto_ai_bot.utils.metrics import export_as_text  # type: ignore
            return PlainTextResponse(export_as_text(), media_type="text/plain; version=0.0.4")
        except Exception:
            return PlainTextResponse("# no metrics exporter wired\n", media_type="text/plain")

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        c = app.state.container
        if not telegram_handle_update:
            return JSONResponse({"ok": False, "error": "telegram adapter not available"}, status_code=status.HTTP_501_NOT_IMPLEMENTED)

        # простая проверка секрета из query (?secret=...)
        secret = request.query_params.get("secret")
        if secret != c.settings.TELEGRAM_BOT_SECRET:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)

        try:
            payload = await request.json()
        except Exception:
            body = await request.body()
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                return JSONResponse({"ok": False, "error": "invalid json"}, status_code=status.HTTP_400_BAD_REQUEST)

        try:
            # унифицированная сигнатура: (container, payload)
            await telegram_handle_update(c, payload)  # type: ignore[arg-type]
            return JSONResponse({"ok": True})
        except Exception as e:
            logger.exception("telegram handler failed: %s", e)
            return JSONResponse({"ok": False, "error": "internal"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return app


# Uvicorn entrypoint:
# uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8080
app = create_app()
