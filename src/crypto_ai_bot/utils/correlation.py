# src/crypto_ai_bot/utils/correlation.py
from __future__ import annotations
import uuid
from contextvars import ContextVar
from typing import Optional, Dict, Any

_cid: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

def new_id() -> str:
    return uuid.uuid4().hex

def set_id(cid: Optional[str]) -> None:
    _cid.set(cid or new_id())

def get_id() -> Optional[str]:
    return _cid.get()

def context() -> Dict[str, Any]:
    return {"correlation_id": get_id()}
