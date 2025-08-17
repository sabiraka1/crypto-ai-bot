# src/crypto_ai_bot/core/types/events.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Event:
    type: str
    payload: Dict[str, Any]
