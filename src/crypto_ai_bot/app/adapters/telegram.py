from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

from ...core.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.utils.logging import get_logger

router = APIRouter(prefix="/telegram", tags=["telegram"])
_log = get_logger("telegram")

def _header(req: Request, name: str) -> Optional[str]:
    v = req.headers.get(name)
    return v if v is not None else None

def _verify_signature(req: Request, body: bytes, token: str) -> bool:
    """1) точное совпадение X-Telegram-Bot-Api-Secret-Token; 2) HMAC по токену (fallback)."""
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

    # команды: /buy [amt], /sell
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    force = cmd if cmd in {"buy", "sell"} else None

    # единичный шаг торгового пайплайна
    try:
        await eval_and_execute(
            symbol=c.settings.SYMBOL,
            storage=c.storage,
            broker=c.broker,
            bus=c.bus,
            exchange=c.settings.EXCHANGE,
            fixed_quote_amount=c.settings.FIXED_AMOUNT,
            idempotency_bucket_ms=c.settings.IDEMPOTENCY_BUCKET_MS,
            idempotency_ttl_sec=c.settings.IDEMPOTENCY_TTL_SEC,
            risk_manager=c.risk,
            protective_exits=c.exits,
            force_action=force,
        )
    except Exception as exc:
        _log.error("telegram_eval_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="eval_failed")

    await _send_message(token, chat_id, "✅ Команда принята" if force else "ℹ️ Запрос обработан")
    return {"ok": True}
