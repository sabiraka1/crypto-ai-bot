# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status, Depends
from fastapi.routing import APIRouter

from crypto_ai_bot.app.middleware import RateLimitMiddleware
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.utils.time import now_ms

logger = logging.getLogger(__name__)
app = FastAPI()

# Входной rate-limit + request_id
app.add_middleware(RateLimitMiddleware, global_rps=20)

# DI
_container = build_container()
settings = _container.settings
bus = _container.bus
repos = _container.repos
orchestrator = _container.orchestrator

router = APIRouter()


@router.get("/health")
async def health() -> Dict[str, Any]:
    """
    Базовый health + расширенные проверки:
    - DB ping (SELECT 1)
    - Bus stats (если есть)
    - Last successful ticks (eval/exits/reconcile)
    """
    db_ok = True
    try:
        conn = _container.db  # ожидается sqlite_adapter.connect(...) в compose
        cur = conn.execute("SELECT 1")
        _ = cur.fetchone()
    except Exception as e:
        db_ok = False
        logger.warning("DB health failed: %s", e)

    bus_stats = {}
    try:
        # если в нашей шине есть stats()
        if hasattr(bus, "stats") and callable(bus.stats):
            bus_stats = bus.stats()
    except Exception as e:
        logger.warning("Bus stats failed: %s", e)

    # Оркестратор хранит отметки последних успешных тиков (если добавлено в Orchestrator)
    last = {}
    for k in ("eval", "exits", "reconcile"):
        v = getattr(orchestrator, f"last_{k}_ok_ms", None)
        if v:
            last[k] = v

    return {
        "ok": db_ok and True,
        "db_ok": db_ok,
        "bus": bus_stats,
        "ticks": last,
        "ts": now_ms(),
        "mode": settings.MODE,
        "trading_enabled": bool(getattr(settings, "ENABLE_TRADING", False)),
    }


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    """
    Вебхук Telegram: только POST и с проверкой секрета.
    Секрет — TELEGRAM_BOT_SECRET (в settings).
    """
    secret = request.headers.get("X-Telegram-Secret") or request.query_params.get("secret")
    if not secret or secret != settings.TELEGRAM_BOT_SECRET:
        return Response(status_code=status.HTTP_403_FORBIDDEN, content="Forbidden")

    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        payload = {}

    # адаптер ожидает сигнатуру handle_update(container, payload)
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update
    try:
        await tg_handle_update(_container, payload)
    except Exception as e:
        logger.exception("telegram handle failed: %s", e)
        return Response(status_code=500, content="handler error")

    return Response(status_code=200, content="ok")


@router.get("/")
async def root() -> Dict[str, Any]:
    return {"name": "crypto-ai-bot", "mode": settings.MODE, "ok": True}


app.include_router(router)


@app.on_event("startup")
async def _on_startup() -> None:
    logger.info("Starting orchestrator and bus...")
    await bus.start()
    await orchestrator.start()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    logger.info("Stopping orchestrator and bus...")
    await orchestrator.stop()
    await bus.stop()
