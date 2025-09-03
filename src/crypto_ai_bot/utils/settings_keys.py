from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar


T = TypeVar("T")

def per_symbol_override(settings: Any, symbol: str, base_key: str, caster: Callable[[str], T], default: T) -> T:
    """
    Ğ˜Ñ‰ĞµÑ‚ ĞºĞ»ÑÑ‡ Ğ²Ğ¸Ğ´Ğ° BASEKEY_BASE_QUOTE Ñ Ğ¿Ğ°Ğ´Ğ´Ğ¸Ğ½Ğ³Ğ¾Ğ¼ ÑĞ¸Ğ¼Ğ²Ğ¾Ğ»Ğ°.
    Ğ•ÑĞ»Ğ¸ Ğ½Ğ°Ğ¹Ğ´ĞµĞ½ Ğ¸ Ğ²Ğ°Ğ»Ğ¸Ğ´Ğ½Ñ‹Ğ¹ â€” ĞºĞ°ÑÑ‚ÑƒĞµĞ¼ Ğ¸ Ğ²Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµĞ¼; Ğ¸Ğ½Ğ°Ñ‡Ğµ â€” Ğ±ĞµÑ€Ñ‘Ğ¼ base_key Ğ¸Ğ»Ğ¸ default.
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
