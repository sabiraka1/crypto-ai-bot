# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .interfaces import UnitOfWork
from .migrations.runner import apply_all


def connect(path: str | Path) -> sqlite3.Connection:
    p = str(path)
    con = sqlite3.connect(p, check_same_thread=False, isolation_level=None)  # autocommit off; будем управлять вручную
    con.row_factory = sqlite3.Row
    # режимы производительности/устойчивости
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    # убедимся, что схема применена
    apply_all(con)
    return con


@contextmanager
def in_txn(con: sqlite3.Connection) -> Iterator[None]:
    try:
        con.execute("BEGIN IMMEDIATE;")
        yield
        con.execute("COMMIT;")
    except Exception:
        try:
            con.execute("ROLLBACK;")
        except Exception:
            pass
        raise


class SqliteUnitOfWork(UnitOfWork):
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def transaction(self):
        return in_txn(self._con)


# ────────── Утилиты сериализации Decimal/JSON (если нужно) ──────────

def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def now_ms() -> int:
    return int(time.time() * 1000)
