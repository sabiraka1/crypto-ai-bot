# src/crypto_ai_bot/core/types/events.py
from __future__ import annotations
from typing import TypedDict, Dict, Any, Optional
from .base import Millis

class Event(TypedDict, total=False):
    type: str
    ts_ms: Millis
    request_id: Optional[str]
    correlation_id: Optional[str]
    payload: Dict[str, Any]
