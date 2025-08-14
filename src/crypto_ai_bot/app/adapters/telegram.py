# -*- coding: utf-8 -*-
"""
Thin Telegram adapter (Phase 1).
Единая точка импорта: crypto_ai_bot.app.adapters.telegram.process_update
Пока проксирует к существующему telegram/bot.py
"""
from __future__ import annotations
from typing import Any, Dict

try:
    from crypto_ai_bot.telegram.bot import process_update as _legacy_process_update  # type: ignore
except Exception:
    _legacy_process_update = None

def process_update(payload: Dict[str, Any]) -> None:
    if _legacy_process_update:
        return _legacy_process_update(payload)
    # если легаси отсутствует — тихий no-op
    return None


