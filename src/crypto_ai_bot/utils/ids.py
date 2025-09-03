from __future__ import annotations

import secrets
import time


def make_client_order_id(exchange_id: str, tag: str) -> str:
    """Ğ‘ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ñ‹Ğ¹ clientOrderId: Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ [a-zA-Z0-9_-]."""
    ms = int(time.time() * 1000)
    rnd = secrets.token_hex(4)
    safe_tag = "".join(ch if ch.isalnum() else "-" for ch in tag)[:32]
    safe_ex = "".join(ch if ch.isalnum() else "-" for ch in exchange_id)[:16]
    return f"{safe_ex}-{safe_tag}-{ms}-{rnd}"


def sanitize_ascii(value: str) -> str:
    """Ğ¤Ğ¸Ğ»ÑŒÑ‚Ñ€ÑƒĞµÑ‚ ÑÑ‚Ñ€Ğ¾ĞºÑƒ, Ğ¾ÑÑ‚Ğ°Ğ²Ğ»ÑÑ Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ Ğ±ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ñ‹Ğµ ASCII ÑĞ¸Ğ¼Ğ²Ğ¾Ğ»Ñ‹ [a-z0-9-]."""
    return "".join(
        ch.lower() if ch.isalnum() else "-"
        for ch in value
        if ch.isalnum() or ch in "-_"
    )
