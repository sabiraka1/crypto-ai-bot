from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def per_symbol_override(
    settings: Any, symbol: str, base_key: str, caster: Callable[[str], T], default: T
) -> T:
    """
    Get per-symbol override from settings: BASEKEY_BASE_QUOTE.
    Falls back to base_key if symbol-specific not found, then to default.
    """
    # Normalize symbol for settings key
    s = (symbol or "").upper().replace("/", "_").replace("-", "_")
    skey = f"{base_key}_{s}".upper()

    # Try symbol-specific setting first
    raw = getattr(settings, skey, None)
    if raw not in (None, ""):
        try:
            return caster(str(raw))
        except Exception:
            pass  # Fall through to base key

    # Try base setting
    raw2 = getattr(settings, base_key, None)
    if raw2 not in (None, ""):
        try:
            return caster(str(raw2))
        except Exception:
            pass  # Fall through to default

    return default
