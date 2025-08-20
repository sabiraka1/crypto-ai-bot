# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations
import re
import time
from hashlib import blake2b
from typing import Optional

_KEY_RE = re.compile(r"^[A-Za-z0-9:_\-/\.]{8,160}$")

def now_ms() -> int:
    return int(time.time() * 1000)

def bucket_ms(ts_ms: int, width_ms: int) -> int:
    if width_ms <= 0:
        return ts_ms
    return (ts_ms // width_ms) * width_ms

def validate_key(key: str) -> bool:
    return bool(key and _KEY_RE.match(key))

def _h(s: str) -> str:
    # short stable hash (<=12 chars)
    return blake2b(s.encode("utf-8"), digest_size=6).hexdigest()

def build_key(
    *,
    kind: str,              # e.g. "order"
    symbol: str,            # e.g. "BTC/USDT"
    side: str,              # "buy" | "sell"
    ts_ms: int,
    bucket_width_ms: int,
    decision_id: Optional[str] = None,
) -> str:
    b = bucket_ms(ts_ms, bucket_width_ms)
    parts = [kind, symbol.replace("/", "-"), side, str(b)]
    if decision_id:
        parts.append(_h(decision_id))
    key = ":".join(parts)
    return key if validate_key(key) else _h(key)

# Adapter-friendly helpers (used by repos/use-cases)

def reserve(repo, key: str, ttl_ms: int) -> bool:
    """
    Try to reserve the key for ttl_ms. Returns False if duplicate/replay.
    Repo is expected to implement: check_and_store(key: str, ttl_ms: int) -> bool
    """
    if not validate_key(key):
        return False
    return repo.check_and_store(key, ttl_ms=ttl_ms)

def commit(repo, key: str) -> None:
    """
    Mark key as successfully used (terminal). Repo should implement commit(key: str) -> None
    """
    if validate_key(key):
        try:
            repo.commit(key)
        except Exception:
            # commit is best-effort; do not fail trading path
            pass

def rollback(repo, key: str) -> None:
    """
    Optional: free reservation. Repo may implement rollback(key: str) -> None
    """
    if validate_key(key):
        try:
            # If repo provides rollback/unlock — call it; otherwise ignore silently
            fn = getattr(repo, "rollback", None)
            if callable(fn):
                fn(key)
        except Exception:
            pass
