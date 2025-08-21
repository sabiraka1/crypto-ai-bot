## `adapters/telegram.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Request, HTTPException
from ..compose import Container
from ...core.use_cases.eval_and_execute import eval_and_execute
from ...core.events import topics
from ...utils.logging import get_logger
from ...utils.ids import sanitize_ascii
router = APIRouter()
_log = get_logger("adapters.telegram")
@dataclass(frozen=True)
class TgMessage:
    chat_id: str
    text: str
def _parse_command(text: str) -> Tuple[str, Optional[Decimal]]:
    parts = (text or "").strip().split()
    if not parts:
        return "eval", None
    cmd = parts[0].lower()
    if cmd == "/buy" and len(parts) >= 2:
        try:
            return "buy", Decimal(parts[1])
        except Exception:
            return "buy", None
    if cmd == "/sell":
        if len(parts) >= 2:
            try:
                return "sell", Decimal(parts[1])
            except Exception:
                return "sell", None
        return "sell", None
    return "eval", None
@router.post("/webhook")
async def webhook(request: Request):
    c: Container = request.app.state.container
    if not c.settings.TELEGRAM_ENABLED:
        raise HTTPException(status_code=403, detail="telegram disabled")
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    msg = (body.get("message") or {})
    chat = (msg.get("chat") or {})
    chat_id = str(chat.get("id") or "")
    text = str(msg.get("text") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="no chat id")
    command, amount = _parse_command(text)
    await c.bus.publish(topics.DECISION_EVALUATED, {"from": "telegram", "command": command, "amount": str(amount or "")}, key=c.settings.SYMBOL)
    res = await eval_and_execute(
        symbol=c.settings.SYMBOL,
        storage=c.storage,
        broker=c.broker,  # type: ignore[arg-type]
        bus=c.bus,
        exchange=c.settings.EXCHANGE,
        fixed_quote_amount=c.settings.FIXED_AMOUNT,
        idempotency_bucket_ms=c.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=c.settings.IDEMPOTENCY_TTL_SEC,
        risk_manager=c.risk,
        protective_exits=c.exits,
        force_action=(command if command in {"buy", "sell"} else None),
        force_amount=amount,
    )
    return {
        "ok": True,
        "action": res.action,
        "decision": res.evaluation.decision,
        "score": res.evaluation.score,
    }