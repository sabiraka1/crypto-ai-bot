# src/crypto_ai_bot/app/server.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.app.middleware import RateLimitMiddleware
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

# Загружаем единый инстанс настроек один раз (без прямого os.environ вне Settings)
_SETTINGS = Settings.load()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Сборка DI-контейнера
    container = build_container(settings=_SETTINGS)
    app.state.settings = _SETTINGS
    app.state.container = container

    # Старт инфраструктуры
    try:
        bus = getattr(container, "bus", None)
        if bus and hasattr(bus, "start"):
            await bus.start()

        orchestrator = getattr(container, "orchestrator", None)
        if orchestrator and hasattr(orchestrator, "start"):
            await orchestrator.start()

        yield

    except Exception as e:
        logger.exception("lifespan startup error: %s", e)
        # Если ошибка на старте — корректно дойдём до shutdown-блока
        yield
    finally:
        # Graceful shutdown
        try:
            orchestrator = getattr(app.state.container, "orchestrator", None)
            if orchestrator and hasattr(orchestrator, "stop"):
                await orchestrator.stop()
        except Exception:
            logger.exception("orchestrator stop failed")

        try:
            bus = getattr(app.state.container, "bus", None)
            if bus and hasattr(bus, "stop"):
                await bus.stop()
        except Exception:
            logger.exception("event bus stop failed")


app = FastAPI(title="crypto-ai-bot", version="1.0.0", lifespan=lifespan)

# Глобальный входной rate-limit (ASGI)
app.add_middleware(RateLimitMiddleware, settings=_SETTINGS)


@app.get("/health")
async def health() -> Dict[str, Any]:
    c = app.state.container
    s: Settings = app.state.settings
    # Лёгкий health: без запросов к бирже/БД — это liveness
    return {
        "ok": True,
        "mode": getattr(s, "MODE", "paper"),
        "exchange": getattr(s, "EXCHANGE", "gateio"),
        "telegram": bool(getattr(s, "TELEGRAM_BOT_TOKEN", "")),
        "orchestrator": bool(getattr(c, "orchestrator", None)),
        "bus": bool(getattr(c, "bus", None)),
    }


@app.get("/telegram")
async def telegram_probe() -> Dict[str, Any]:
    # не вебхук — просто быстрый пробник, чтобы 405 не светился в логах
    return {"ok": True, "hint": "use POST /telegram for webhook"}


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    """
    Telegram webhook:
      - проверяем секрет (заголовок X-Telegram-Bot-Api-Secret-Token или query ?secret=)
      - проксируем апдейт в адаптер handle_update(container, payload)
    """
    s: Settings = app.state.settings
    cont = app.state.container

    # секьюрная проверка секрета
    provided = (
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        or request.query_params.get("secret")
        or ""
    )
    expected = getattr(s, "TELEGRAM_BOT_SECRET", "") or ""
    if expected and provided != expected:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED, content="invalid secret")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("telegram webhook: invalid JSON")
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="invalid json")

    try:
        await telegram_handle_update(cont, payload)
        return Response(status_code=status.HTTP_200_OK, content="ok")
    except Exception as e:
        logger.exception("telegram handler failed: %s", e)
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content="handler error")
