from __future__ import annotations

from typing import Any, Dict, Optional
import time
import logging
import sqlite3

from .sqlite_adapter import (
    apply_connection_pragmas,
    snapshot_metrics,
    execute,
)

log = logging.getLogger(__name__)


def cleanup_idempotency(id_repo: Any, now_ms: Optional[int] = None) -> int:
    """
    Чистит просроченные ключи идемпотентности.
    Сначала пытается вызвать метод репозитория (если он реализован),
    иначе выполняет прямой SQL как запасной вариант.

    Возвращает количество удалённых записей.
    """
    now_ms = now_ms or int(time.time() * 1000)

    # Предпочтительно — через репозиторий
    if hasattr(id_repo, "cleanup_expired") and callable(id_repo.cleanup_expired):
        try:
            return int(id_repo.cleanup_expired(now_ms=now_ms))
        except Exception as e:
            log.debug("idempotency repo cleanup_expired failed, fallback to SQL: %s", e)

    # Fallback — прямой SQL (должна быть таблица idempotency с expires_at_ms)
    conn: Optional[sqlite3.Connection] = getattr(getattr(id_repo, "__dict__", {}), "con", None) \
        or getattr(id_repo, "con", None)
    if not isinstance(conn, sqlite3.Connection):
        log.warning("cleanup_idempotency: no sqlite connection available in repository")
        return 0

    cur = execute(
        conn,
        "DELETE FROM idempotency WHERE expires_at_ms IS NOT NULL AND expires_at_ms < ?",
        (now_ms,),
    )
    try:
        return cur.rowcount or 0
    finally:
        cur.close()


def checkpoint_and_optimize(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Дружелюбный к продакшену чекпоинт WAL + сбор метрик/показателей БД.
    - НЕ делает VACUUM (он блокирующий), только wal_checkpoint(PASSIVE) внутри snapshot_metrics.
    - Выполняет PRAGMA optimize.
    """
    # PRAGMA optimize (неблокирующая оптимизация планировщика)
    try:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA optimize;")
        finally:
            cur.close()
    except Exception as e:
        log.debug("PRAGMA optimize failed: %s", e)

    # Метрики и checkpoint (в snapshot_metrics уже есть wal_checkpoint(PASSIVE))
    return snapshot_metrics(conn)


def apply_safe_pragmas(conn: sqlite3.Connection) -> None:
    """
    Применяет безопасные PRAGMA (WAL, synchronous=NORMAL, busy_timeout, и т.д.).
    Идempotent — можно вызывать при старте и периодически.
    """
    apply_connection_pragmas(conn)


def maintenance_once(
    *,
    conn: sqlite3.Connection,
    idempotency_repo: Any,
    apply_pragmas: bool = False,
) -> Dict[str, Any]:
    """
    Одна итерация техобслуживания:
      - (опционально) применяет безопасные PRAGMA
      - чистит просроченные idempotency-ключи
      - делает checkpoint/optimize и возвращает метрики БД

    Возвращает словарь с краткой сводкой.
    """
    if apply_pragmas:
        try:
            apply_safe_pragmas(conn)
        except Exception as e:
            log.debug("apply_safe_pragmas failed: %s", e)

    removed = 0
    try:
        removed = cleanup_idempotency(id_repo=idempotency_repo)
    except Exception as e:
        log.exception("cleanup_idempotency failed: %s", e)

    dbm = {}
    try:
        dbm = checkpoint_and_optimize(conn)
    except Exception as e:
        log.debug("checkpoint_and_optimize failed: %s", e)

    return {
        "idempotency_removed": removed,
        "db_metrics": dbm,
    }
