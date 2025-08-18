from __future__ import annotations
import sqlite3
from typing import Any

def connect(path: str) -> sqlite3.Connection:
    """
    Подключение SQLite в autocommit (isolation_level=None) с безопасными параметрами.
    """
    # Встроенный таймаут соединения; retry делает сам SQLite (busy_timeout мы задаём через PRAGMA)
    con = sqlite3.connect(
        path,
        isolation_level=None,      # autocommit — нам удобно для VACUUM/DDL
        check_same_thread=False,   # доступ из разных потоков
        timeout=30.0,              # базовый таймаут на открытие/блокировки
        detect_types=0,
    )
    # По умолчанию row-фабрику не меняем (минимальная совместимость)
    return con
