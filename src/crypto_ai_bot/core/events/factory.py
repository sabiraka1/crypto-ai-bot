from __future__ import annotations
from typing import Dict

from .async_bus import AsyncBus
from . import DEFAULT_BACKPRESSURE_MAP

def build_bus(cfg) -> AsyncBus:
    """Factory for AsyncBus using strategies from Settings (if provided).
    cfg.EVENT_BACKPRESSURE_MAP may override domain defaults.
    """
    overrides: Dict[str, str] = {}
    try:
        # start with recommended defaults
        overrides.update(DEFAULT_BACKPRESSURE_MAP)
        # apply user overrides from settings (validated there)
        user_map = getattr(cfg, "EVENT_BACKPRESSURE_MAP", None) or {}
        overrides.update(user_map)
    except Exception:
        pass
    return AsyncBus(backpressure_overrides=overrides)
