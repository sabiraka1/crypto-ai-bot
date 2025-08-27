from __future__ import annotations

import time
import secrets
import hashlib


def make_client_order_id(exchange_id: str, tag: str) -> str:
    """Безопасный clientOrderId: только [a-zA-Z0-9_-]."""
    ms = int(time.time() * 1000)
    rnd = secrets.token_hex(4)
    safe_tag = "".join(ch if ch.isalnum() else "-" for ch in tag)[:32]
    safe_ex = "".join(ch if ch.isalnum() else "-" for ch in exchange_id)[:16]
    return f"{safe_ex}-{safe_tag}-{ms}-{rnd}"


def sanitize_ascii(value: str) -> str:
    """Фильтрует строку, оставляя только безопасные ASCII символы [a-z0-9-]."""
    return "".join(
        ch.lower() if ch.isalnum() else "-"
        for ch in value
        if ch.isalnum() or ch in "-_"
    )