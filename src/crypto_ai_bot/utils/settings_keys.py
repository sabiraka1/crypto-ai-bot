from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def per_symbol_override(
    settings: Any, symbol: str, base_key: str, caster: Callable[[str], T], default: T
) -> T:
    """
    ѵ ю  BASEKEY_BASE_QUOTE с  с.
    с   ѹ  сѵ  ѰѰ; ѵ  Ѽ base_key  default.
    """
    s = (symbol or "").upper().replace("/", "_").replace("-", "_")
    skey = f"{base_key}_{s}".upper()
    raw = getattr(settings, skey, None)
    if raw not in (None, ""):
        try:
            return caster(str(raw))
        except Exception:
            pass
    raw2 = getattr(settings, base_key, None)
    if raw2 not in (None, ""):
        try:
            return caster(str(raw2))
        except Exception:
            pass
    return default
