
from __future__ import annotations
import asyncio
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.utils.metrics import inc

async def cleanup_idempotency_once(cfg, ttl_seconds: int = 3600) -> None:
    con = connect(cfg.DB_PATH)
    try:
        repo = SqliteIdempotencyRepository(con)
        n = repo.cleanup_expired(ttl_seconds=ttl_seconds)
        if n:
            inc("idempotency_purged_total", {"count": str(n)})
    finally:
        try:
            con.close()
        except Exception:
            pass
