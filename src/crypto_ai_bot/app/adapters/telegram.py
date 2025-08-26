from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException

from ...utils.logging import get_logger

router = APIRouter(prefix="/telegram", tags=["telegram"])
_log = get_logger("telegram")


def _header(req: Request, name: str) -> Optional[str]:
    v = req.headers.get(name)
    return v if v is not None else None


def _verify_signature(req: Request, body: bytes, token: str) -> bool:
    """Два варианта: 1) точное совпадение X-Telegram-Bot-Api-Secret-Token; 2) HMAC по токену (fallback)."""
    header = _header(req, "X-Telegram-Bot-Api-Secret-Token")
    if header and header == token:
        return True
    try:
        secret = hashlib.sha256(token.encode()).digest()
        sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return sig == _header(req, "X-Telegram-Signature")
    except Exception:
        return False


async def _send_message(token: str, chat_id: str, text: str) -> None:
    try:
        import httpx  # type: ignore
    except Exception:
        _log.warning("httpx_not_installed_skip_reply")
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )


@router.post("/webhook")
async def webhook(request: Request):
    # настройка
    c = request.app.state.container
    if not getattr(c.settings, "TELEGRAM_ENABLED", False):
        raise HTTPException(status_code=403, detail="telegram disabled")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="no telegram token configured")

    raw = await request.body()
    if not _verify_signature(request, raw, token):
        raise HTTPException(status_code=401, detail="invalid signature")

    body = await request.json()
    msg = body.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = str(msg.get("text", "")).strip()

    # простейший парсер команд
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    amount = None
    if len(parts) >= 2:
        try:
            from decimal import Decimal
            amount = Decimal(parts[1])
        except Exception:
            amount = None

    # форс-действие
    force = cmd if cmd in {"buy", "sell"} else None

    # запуск «одного шага» — используем существующий use-case
    res = await c.orchestrator._eval_loop().__anext__()  # не трогаем: здесь лучше вызвать прикладной UC напрямую
    # ⚠️ Если у тебя есть отдельный use-case для ручного запуска — подставь его сюда (eval_and_execute/execute_trade)

    # ответ пользователю
    text = "✅ Команда принята" if force else "ℹ️ Запрос обработан"
    await _send_message(token, chat_id, text)
    return {"ok": True}
