# src/crypto_ai_bot/telegram/bot.py
"""
Telegram webhook router for FastAPI.
Даёт эндпоинты:
- POST /telegram/webhook?token=...  — принимает апдейты от Telegram
- GET  /telegram/ping               — быстрый пинг для проверки
- GET  /telegram/webhook            — health of webhook mount
"""

from __future__ import annotations

import os
import logging
import inspect
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

# Импорт твоей логики команд. Оставляем как есть — внутри можешь делать что угодно.
from crypto_ai_bot.telegram.commands import process_command  # noqa: F401

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

# Секрет для верификации вебхука
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "")

def _need_token() -> bool:
    # Если секрет задан — требуем токен в query
    return bool(TELEGRAM_SECRET_TOKEN)

@router.get("/telegram/ping")
async def telegram_ping() -> Dict[str, Any]:
    return {"ok": True, "service": "telegram", "has_secret": _need_token()}

@router.get("/telegram/webhook")
async def telegram_webhook_health(token: str | None = None) -> Dict[str, Any]:
    if _need_token() and token != TELEGRAM_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return {"ok": True, "webhook": "ready"}

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, token: str | None = None) -> JSONResponse:
    """
    Основной вход от Telegram.
    Пробрасывает update в твою process_command().
    """
    if _need_token() and token != TELEGRAM_SECRET_TOKEN:
        return JSONResponse(status_code=403, content={"ok": False, "error": "Invalid token"})

    try:
        update = await request.json()
    except Exception as e:
        logger.exception("Failed to parse Telegram update JSON: %s", e)
        return JSONResponse(status_code=400, content={"ok": False, "error": "Bad JSON"})

    # Аккуратно вызываем process_command — поддержка sync/async
    try:
        if inspect.iscoroutinefunction(process_command):
            await process_command(update)  # type: ignore[misc]
        else:
            # если sync — исполним в threadpool, чтобы не блокировать event loop
            await run_in_threadpool(process_command, update)  # type: ignore[misc]
    except Exception as e:
        logger.exception("process_command failed: %s", e)
        return JSONResponse(status_code=200, content={"ok": True, "handled": False, "error": str(e)})

    return JSONResponse(status_code=200, content={"ok": True, "handled": True})


__all__ = ["router"]
