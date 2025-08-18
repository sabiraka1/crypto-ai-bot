# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics


def connect(path: str) -> sqlite3.Connection:
    """
    Создаёт соединение c SQLite и включает безопасные PRAGMA.
    """
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    cur = con.cursor()

    # WAL + настройки безопасности/производительности
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    try:
        cur.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    try:
        cur.execute("PRAGMA temp_store=MEMORY;")
    except Exception:
        pass
    try:
        cur.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    try:
        cur.execute("PRAGMA mmap_size=268435456;")  # ~256MB, noop если не поддерживается
    except Exception:
        pass

    cur.close()
    return con


def _int(row: Any, idx: int, default: int = 0) -> int:
    try:
        return int(row[idx])
    except Exception:
        return default


def _get_db_file_size_bytes(path_hint: Optional[str]) -> Optional[int]:
    if not path_hint or str(path_hint).startswith(":"):
        return None
    try:
        return int(os.path.getsize(path_hint))
    except Exception:
        return None


def _wal_checkpoint(con: sqlite3.Connection) -> None:
    try:
        con.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except Exception:
        pass


def _page_stats(con: sqlite3.Connection) -> Dict[str, int]:
    page_size = page_count = freelist_count = 0
    try:
        page_size = int(con.execute("PRAGMA page_size;").fetchone()[0])
    except Exception:
        pass
    try:
        page_count = int(con.execute("PRAGMA page_count;").fetchone()[0])
    except Exception:
        pass
    try:
        freelist_count = int(con.execute("PRAGMA freelist_count;").fetchone()[0])
    except Exception:
        pass
    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
    }


def snapshot_metrics(con: sqlite3.Connection, path_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Снимает срез показателей SQLite и публикует в utils.metrics.

    Экспортируемые метрики (Prometheus-совместимые):
      - sqlite_page_size_bytes
      - sqlite_page_count
      - sqlite_freelist_count
      - sqlite_file_size_bytes
      - sqlite_freelist_bytes
      - sqlite_fragmentation_percent
      - sqlite_wal_frames_total
      - sqlite_wal_checkpoint_last_ms
    """
    t0 = time.perf_counter()

    # 1) Page stats
    st = _page_stats(con)
    page_size = int(st["page_size"])
    page_count = int(st["page_count"])
    freelist_count = int(st["freelist_count"])

    metrics.gauge("sqlite_page_size_bytes", float(page_size))
    metrics.gauge("sqlite_page_count", float(page_count))
    metrics.gauge("sqlite_freelist_count", float(freelist_count))

    # 2) File metrics (если база не :memory:)
    file_size = _get_db_file_size_bytes(path_hint)
    if file_size is not None:
        metrics.gauge("sqlite_file_size_bytes", float(file_size))
        freelist_bytes = int(freelist_count * page_size) if page_size and freelist_count else 0
        metrics.gauge("sqlite_freelist_bytes", float(freelist_bytes))
        frag_pct = (100.0 * freelist_bytes / file_size) if file_size > 0 else 0.0
        metrics.gauge("sqlite_fragmentation_percent", float(frag_pct))
    else:
        # для :memory: публикуем нули
        metrics.gauge("sqlite_file_size_bytes", 0.0)
        metrics.gauge("sqlite_freelist_bytes", 0.0)
        metrics.gauge("sqlite_fragmentation_percent", 0.0)

    # 3) WAL info
    wal_frames = 0
    try:
        row = con.execute("PRAGMA wal_checkpoint(PASSIVE);").fetchone()
        # Формат: (busy, log, checkpointed)
        if row:
            # количество фреймов в WAL доступно как row[1] (log frames)
            wal_frames = _int(row, 1, 0)
    except Exception:
        pass
    metrics.gauge("sqlite_wal_frames_total", float(wal_frames))

    # время самого snapshot (для наблюдаемости)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metrics.gauge("sqlite_wal_checkpoint_last_ms", float(elapsed_ms))

    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "file_size_bytes": file_size,
        "wal_frames": wal_frames,
        "elapsed_ms": elapsed_ms,
    }
