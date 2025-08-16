from __future__ import annotations
from typing import Optional, Dict, Any
from decimal import Decimal

def make_idempotency_key(*, symbol: str, side: str, size: Decimal, ts_ms: int, decision_id: str) -> str:
    # key spec: {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    minute_bucket = ts_ms // 60000
    return f"{symbol}:{side}:{size}:{minute_bucket}:{decision_id[:8]}"

def check_and_store(repo, key: str) -> bool:
    """Try to claim key. Returns True if we just claimed it (first execution),
    False if it already exists and should not be executed again."""
    if repo is None:
        return True
    try:
        return bool(repo.claim(key))
    except Exception:
        # fail-open: better to allow single execution than block forever due to storage error
        return True
