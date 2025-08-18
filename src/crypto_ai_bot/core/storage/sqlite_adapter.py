# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import os
import sqlite3
from typing import Optional, Dict, Any

from crypto_ai_bot.utils import metrics

def connect(path: str) -> sqlite3.Connection:
    """
    Подключение к SQLite с безопасными PRAGMA и WAL.
    Возвращает готовый Connection.
    """
    con = sqlite3.connect(path, check_same_thread=False)  # FastAPI/async: делим соединение вручную
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def _is_memory_db(path: str) -> bool:
    p = (path or "").strip().lower()
    return p in (":memory:", "") or p.startswith("file::memory:")

def snapshot_metrics(con: sqlite3.Connection, *, path_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Снимает SQLite-метрики и пишет их в registry:
      - sqlite_file_size_bytes
      - sqlite_page_count
      - sqlite_page_size_bytes
      - sqlite_freelist_pages
      - sqlite_fragmentation_percent
      - sqlite_wal_size_bytes (если есть .wal)
    Возвращает словарь со значениями.
    """
    try:
        cur = con.cursor()
        cur.execute("PRAGMA page_count;")
        page_count = int(cur.fetchone()[0])
        cur.execute("PRAGMA page_size;")
        page_size = int(cur.fetchone()[0])
        cur.execute("PRAGMA freelist_count;")
        freelist = int(cur.fetchone()[0])
    except Exception:
        page_count = page_size = freelist = 0

    # путь к файлу: sqlite хранит в connection, но надёжнее принять hint из вызывающего кода
    db_path = path_hint
    if db_path is None:
        try:
            cur = con.execute("PRAGMA database_list;")
            # [seq, name, file]
            rows = list(cur.fetchall())
            if rows and len(rows[0]) >= 3:
                db_path = str(rows[0][2] or "")
        except Exception:
            db_path = None

    is_mem = _is_memory_db(db_path or "")
    file_size = 0
    wal_size = 0
    if not is_mem and db_path:
        try:
            file_size = int(os.path.getsize(db_path))
        except Exception:
            file_size = 0
        # wal рядом с базой
        try:
            wal_path = db_path + "-wal"
            if os.path.exists(wal_path):
                wal_size = int(os.path.getsize(wal_path))
        except Exception:
            wal_size = 0

    frag_pct = 0.0
    try:
        if page_count > 0:
            frag_pct = (float(freelist) / float(page_count)) * 100.0
    except Exception:
        frag_pct = 0.0

    # Публикуем метрики
    metrics.gauge("sqlite_page_count", float(page_count))
    metrics.gauge("sqlite_page_size_bytes", float(page_size))
    metrics.gauge("sqlite_freelist_pages", float(freelist))
    metrics.gauge("sqlite_fragmentation_percent", float(frag_pct))
    metrics.gauge("sqlite_file_size_bytes", float(file_size))
    metrics.gauge("sqlite_wal_size_bytes", float(wal_size))

    return {
        "page_count": page_count,
        "page_size": page_size,
        "freelist_pages": freelist,
        "fragmentation_percent": frag_pct,
        "file_size_bytes": file_size,
        "wal_size_bytes": wal_size,
        "path": db_path,
        "in_memory": is_mem,
    }
