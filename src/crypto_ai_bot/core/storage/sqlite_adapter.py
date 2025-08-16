from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics

# --- Connection ---
def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    con = sqlite3.connect(path, timeout=30.0, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con

@contextmanager
def in_txn(con: sqlite3.Connection):
    """
    BEGIN IMMEDIATE ... COMMIT/ROLLBACK с метрикой времени транзакции.
    """
    t0 = time.perf_counter()
    try:
        con.execute("BEGIN IMMEDIATE;")
        yield con
        con.execute("COMMIT;")
    except Exception:
        try:
            con.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        dt_ms = int((time.perf_counter() - t0) * 1000)
        try:
            metrics.observe("db_txn_ms", dt_ms, {})
        except Exception:
            pass

# --- Maintenance / Stats ---
def perform_maintenance(con: sqlite3.Connection, cfg) -> None:
    """
    Лёгкое обслуживание: optimize; при росте файла — ANALYZE/VACUUM.
    Порог и период берём из Settings, если заданы.
    """
    try:
        con.execute("PRAGMA optimize;")
    except Exception:
        pass

    try:
        cur = con.execute("PRAGMA page_count;")
        page_count = int(cur.fetchone()[0])
        cur = con.execute("PRAGMA page_size;")
        page_size = int(cur.fetchone()[0])
        db_size_mb = (page_count * page_size) / (1024 * 1024)

        metrics.observe("db_size_mb", db_size_mb, {})

        vacuum_mb = float(getattr(cfg, "DB_VACUUM_THRESHOLD_MB", 256))
        analyze_every = int(getattr(cfg, "DB_ANALYZE_EVERY_N_OPS", 0))

        if db_size_mb >= vacuum_mb:
            t0 = time.perf_counter()
            con.execute("VACUUM;")
            dt_ms = int((time.perf_counter() - t0) * 1000)
            metrics.observe("db_vacuum_ms", dt_ms, {})
    except Exception:
        pass

def get_db_stats(con: sqlite3.Connection) -> Dict[str, Any]:
    try:
        page_count = int(con.execute("PRAGMA page_count;").fetchone()[0])
        page_size = int(con.execute("PRAGMA page_size;").fetchone()[0])
        wal_autocheck = con.execute("PRAGMA journal_mode;").fetchone()[0]
        return {
            "page_count": page_count,
            "page_size": page_size,
            "size_mb": (page_count * page_size) / (1024 * 1024),
            "journal_mode": wal_autocheck,
        }
    except Exception:
        return {"error": "stats_unavailable"}
