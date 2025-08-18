import sqlite3
from typing import Optional


def connect(path: str, *, timeout: float = 5.0) -> sqlite3.Connection:
    """
    Подключение SQLite с безопасными прагмами для прод-окружения.
    - WAL журнал — параллельные чтения, меньше блокировок
    - busy_timeout — ждём вместо немедленной ошибки «database is locked»
    - foreign_keys — включены
    - synchronous=NORMAL — баланс надёжность/скорость
    """
    con = sqlite3.connect(
        path,
        isolation_level=None,      # autocommit-подобный режим; транзакции через "with con:"
        check_same_thread=False,   # разрешаем пул/потоки (мы осторожны в репозиториях)
        timeout=timeout
    )
    # Прагмы
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)};")
    except Exception:
        pass
    return con
