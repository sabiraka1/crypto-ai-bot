from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Tuple

from crypto_ai_bot.utils import metrics

# ---------------- Connection & TXN ----------------

def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=30.0, isolation_level=None, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
    # PRAGMAs
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.close()
    return con

@contextmanager
def in_txn(con: sqlite3.Connection):
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE;")
        yield
        cur.execute("COMMIT;")
    except Exception:
        try:
            cur.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        cur.close()

# ---------------- Stats & Maintenance ----------------

def _pragma(con: sqlite3.Connection, name: str) -> int:
    cur = con.cursor()
    cur.execute(f"PRAGMA {name};")
    row = cur.fetchone()
    cur.close()
    return int(row[0]) if row and row[0] is not None else 0

def get_db_stats(con: sqlite3.Connection, path: str) -> Dict[str, float]:
    page_count = _pragma(con, "page_count")
    freelist_count = _pragma(con, "freelist_count")
    page_size = _pragma(con, "page_size") or 4096
    file_bytes = os.path.getsize(path) if os.path.exists(path) else page_count * page_size
    free_bytes = int(freelist_count * page_size)
    used_bytes = max(0, file_bytes - free_bytes)
    free_ratio = (free_bytes / file_bytes) if file_bytes > 0 else 0.0

    # export metrics
    metrics.observe("db_file_bytes_gauge", file_bytes, {})
    metrics.observe("db_free_bytes_gauge", free_bytes, {})
    metrics.observe("db_free_ratio_gauge", free_ratio, {})

    return {
        "page_count": float(page_count),
        "freelist_count": float(freelist_count),
        "page_size": float(page_size),
        "file_bytes": float(file_bytes),
        "free_bytes": float(free_bytes),
        "used_bytes": float(used_bytes),
        "free_ratio": float(free_ratio),
    }

def vacuum(con: sqlite3.Connection) -> None:
    t0 = time.perf_counter()
    cur = con.cursor()
    try:
        cur.execute("VACUUM;")
        metrics.inc("db_vacuum_total", {})
        metrics.observe("db_vacuum_seconds", time.perf_counter() - t0, {})
    finally:
        cur.close()

def analyze(con: sqlite3.Connection) -> None:
    t0 = time.perf_counter()
    cur = con.cursor()
    try:
        cur.execute("ANALYZE;")
        cur.execute("PRAGMA optimize;")
        metrics.inc("db_analyze_total", {})
        metrics.observe("db_analyze_seconds", time.perf_counter() - t0, {})
    finally:
        cur.close()

def perform_maintenance(con: sqlite3.Connection, cfg) -> Dict[str, Any]:
    """
    Решает, требуется ли VACUUM/ANALYZE по порогам из Settings.
    Возвращает словарь с принятыми действиями.
    """
    if not getattr(cfg, "DB_MAINTENANCE_ENABLE", True):
        return {"enabled": False}

    path = getattr(cfg, "DB_PATH", "data/bot.db")
    stats_before = get_db_stats(con, path)

    min_mb = float(getattr(cfg, "DB_VACUUM_MIN_MB", 64))
    free_ratio_thr = float(getattr(cfg, "DB_VACUUM_FREE_RATIO", 0.20))
    analyze_every = int(getattr(cfg, "DB_ANALYZE_EVERY_WRITES", 5000))
    writes = int(getattr(cfg, "DB_WRITES_SINCE_ANALYZE", 0))

    did_vacuum = False
    did_analyze = False
    actions = []

    file_mb = stats_before["file_bytes"] / (1024 * 1024)
    if file_mb >= min_mb and stats_before["free_ratio"] >= free_ratio_thr:
        try:
            vacuum(con)
            did_vacuum = True
            actions.append("vacuum")
        except Exception as e:
            metrics.inc("db_maintenance_errors_total", {"op": "vacuum", "err": type(e).__name__})

    if writes >= analyze_every:
        try:
            analyze(con)
            did_analyze = True
            actions.append("analyze")
            # сброс счётчика (в Settings как mutable — опционально)
            try:
                cfg.DB_WRITES_SINCE_ANALYZE = 0
            except Exception:
                pass
        except Exception as e:
            metrics.inc("db_maintenance_errors_total", {"op": "analyze", "err": type(e).__name__})

    if not did_analyze:
        # легкая оптимизация между анализами
        try:
            cur = con.cursor()
            cur.execute("PRAGMA optimize;")
            cur.close()
            metrics.inc("db_optimize_total", {})
        except Exception:
            pass

    stats_after = get_db_stats(con, path)
    return {
        "enabled": True,
        "actions": actions,
        "before": stats_before,
        "after": stats_after,
    }
