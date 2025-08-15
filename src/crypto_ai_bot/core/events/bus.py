# -*- coding: utf-8 -*-
"""Simple in-proc EventBus (Phase 1)."""
from __future__ import annotations
from typing import Callable, Dict, List, Any

_SUBS: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

def subscribe(event: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    _SUBS.setdefault(event, []).append(handler)

def publish(event: str, payload: Dict[str, Any]) -> None:
    for h in _SUBS.get(event, []):
        try:
            h(payload)
        except Exception:
            pass



