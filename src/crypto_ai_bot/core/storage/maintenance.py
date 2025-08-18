# src/crypto_ai_bot/core/storage/maintenance.py
from __future__ import annotations

import sqlite3
from typing import Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import get_logger

log = get_logger(__name__)


def cleanup_idempotency_once(conn: sqlite3.Connection, *, max_age_sec: int = 3600) -> int:
    """
    Удаляет старые записи идемпотентности и публикует корректные метрики:
      - idempotency_cleanup_last_count (gauge, БЕЗ labels)
      - idempotency_cleanup_runs_total (counter)
    Схему стараемся угадать; если колонок нет — ничего не падает.
    """
    deleted = 0
    try:
        cur = conn.cursor()
        # Пытаемся удалить по наиболее вероятной схеме
        # Вариант 1: есть created_at (в секундах)
        try:
            cur.execute(
                "DELETE FROM idempotency WHERE created_at < strftime('%s','now') - ?",
                (int(max_age_sec),),
            )
            deleted = cur.rowcount if cur.rowcount is not None else 0
        except Exception:
            # Вариант 2: есть ts_ms (в миллисекундах)
            try:
                cur.execute(
                    "DELETE FROM idempotency WHERE ts_ms < (strftime('%s','now') - ?) * 1000",
                    (int(max_age_sec),),
                )
                deleted = cur.rowcount if cur.rowcount is not None else 0
            except Exception:
                deleted = 0
        cur.close()
    except Exception as e:
        log.warning("cleanup_idempotency_once failed: %s: %s", type(e).__name__, e)

    try:
        metrics.gauge("idempotency_cleanup_last_count", float(deleted))
        metrics.inc("idempotency_cleanup_runs_total")
    except Exception:
        pass
    return int(deleted)
