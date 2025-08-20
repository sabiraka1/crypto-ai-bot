# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations
import hashlib
import zlib
from typing import Dict

def stable_crc32(s: str) -> str:
    return format(zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF, "08x")

def sha1_12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def make_order_key(*, symbol: str, side: str, bucket_sec: int) -> str:
    """Не нормализует symbol и не импортирует core — чистая утилита."""
    base = f"{symbol}:{side}:{bucket_sec}"
    return f"order:{stable_crc32(base)}:{sha1_12(base)}"
