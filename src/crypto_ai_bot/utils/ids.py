## `utils/ids.py`
from __future__ import annotations
import hashlib
import os
import re
import uuid
from typing import Optional
from .time import now_ms, bucket_ms
__all__ = [
    "sanitize_ascii",
    "short_hash",
    "make_correlation_id",
    "make_idempotency_key",
    "make_client_order_id",
]
_ALLOWED_RE = re.compile(r"[^a-z0-9-]+")
_CLIENT_ID_LIMITS = {
    "gateio": 64,
}
def sanitize_ascii(text: str) -> str:
    """Lowercase ASCII-only slug with [a-z0-9-].
    Non-ASCII and separators are replaced with '-'. Multiple '-' are collapsed.
    """
    if not isinstance(text, str):
        text = str(text)
    normalized = text.encode("ascii", errors="ignore").decode("ascii")
    normalized = normalized.lower().replace("_", "-").replace("/", "-")
    normalized = _ALLOWED_RE.sub("-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized
def short_hash(text: str, length: int = 12) -> str:
    """Stable lowercase hex hash truncated to the given length (>=6)."""
    if length < 6:
        raise ValueError("length must be >= 6")
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return h[:length]
def make_correlation_id() -> str:
    """Return a UUID4 hex string (no dashes) suitable for logs/headers."""
    return uuid.uuid4().hex
def make_idempotency_key(symbol: str, side: str, window_ms: int, *, ts_ms: Optional[int] = None) -> str:
    """Create a deterministic idempotency key for an order bucket.
    Format: "<symbol>:<side>:<bucket_ms>" where symbol is ASCII-safe (a-z0-9-).
    Example: "btc-usdt:buy:1699920000000"
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if window_ms <= 0:
        raise ValueError("window_ms must be > 0")
    sym = sanitize_ascii(symbol)
    bkt = bucket_ms(ts_ms, window_ms)
    return f"{sym}:{side}:{bkt}"
def make_client_order_id(exchange: str, key: str, *, ts_ms: Optional[int] = None) -> str:
    """Create clientOrderId compatible with the exchange constraints.
    Policy: "t-<short_hash(key)>-<ts_ms>" and enforce ASCII + length.
    Exchange-specific length limits are applied (defaults to 64 if unknown).
    """
    if not exchange:
        raise ValueError("exchange is required")
    if ts_ms is None:
        ts_ms = now_ms()
    base = f"t-{short_hash(key, 12)}-{ts_ms}"
    limit = _CLIENT_ID_LIMITS.get(exchange.lower(), 64)
    safe = sanitize_ascii(base)
    if len(safe) <= limit:
        return safe
    compressed = f"t-{short_hash(safe, 16)}-{str(ts_ms)[-8:]}"
    return compressed[:limit]
