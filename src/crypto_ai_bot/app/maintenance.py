# src/crypto_ai_bot/app/maintenance.py
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.core.storage.sqlite_adapter import snapshot_metrics as sqlite_snapshot
from crypto_ai_bot.core.storage.maintenance import cleanup_idempotency_once

log = get_logger(__name__)


async def maintenance_loop(conn, cfg: Any) -> None:
    """
    Периодическая техобслужка:
      - очистка идемпотентности (без кардинальности метрик)
      - мягкий SQLite snapshot (метрики page_count/file_size/fragmentation)
    Всё оборачиваем в try/except с логом, чтобы не падать фоном.
    """
    period = int(getattr(cfg, "MAINTENANCE_SEC", 60) or 60)
    ttl = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 300) or 300)

    # небольшой стартовый джиттер, чтобы не биться с другими инстансами
    await asyncio.sleep(random.uniform(0, period * 0.25))

    while True:
        t0 = time.perf_counter()
        try:
            deleted = cleanup_idempotency_once(conn, max_age_sec=ttl)
            log.debug("maintenance: idempotency cleanup = %s", deleted)
        except Exception as e:
            log.warning("maintenance: cleanup_idempotency_once failed: %s: %s", type(e).__name__, e)

        try:
            # передаём path через cfg, чтобы посчитать file_size/fragmentation
            _ = sqlite_snapshot(conn, path_hint=getattr(cfg, "DB_PATH", None))
        except Exception as e:
            log.warning("maintenance: sqlite snapshot failed: %s: %s", type(e).__name__, e)

        # «стабильно, но с джиттером» — чтобы не синхронизироваться по времени
        elapsed = time.perf_counter() - t0
        sleep_for = max(5.0, float(period) - elapsed) + random.uniform(0, period * 0.10)
        try:
            await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            # корректное завершение
            break
