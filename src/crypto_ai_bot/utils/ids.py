from __future__ import annotations

import os, time, secrets, hashlib

def _short_rand(n: int = 6) -> str:
    return secrets.token_hex(n // 2)

def make_client_order_id(exchange: str, payload: str) -> str:
    """
    Дет-детерминированный префикс + короткая энтропия.
    Не зависит от ENV (утилям нельзя тянуть ENV по архитектуре).
    """
    ts = int(time.time() * 1000)
    base = f"{exchange}:{payload}:{ts}:{_short_rand(6)}"
    # короткий суффикс для CCXT ограничений по длине
    h = hashlib.blake2s(base.encode("utf-8"), digest_size=6).hexdigest()
    return f"{exchange}-{h}"
