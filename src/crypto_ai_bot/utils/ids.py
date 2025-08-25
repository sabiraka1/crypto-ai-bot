from __future__ import annotations

import hashlib
from typing import Optional

from .time import now_ms, bucket_ms


def short_hash(s: str, *, n: int = 8) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n]


def make_client_order_id(exchange: str, extra: str) -> str:
    """Формат для Gate.io/CCXT: t-<xh>-<tsms> с коротким префиксом.
    Пример: t-1a2b3c4d-1700000000000
    """
    return f"t-{short_hash(exchange + ':' + extra)}-{now_ms()}"


def make_idempotency_key(symbol: str, action: str, bucket_window_ms: int) -> str:
    b = bucket_ms(now_ms(), bucket_window_ms)
    return f"{symbol}:{action}:{b}"