# src/crypto_ai_bot/core/storage/sqlite_adapter.py
import sqlite3
import time

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    return _RetryingConnection(con)

class _RetryingConnection(sqlite3.Connection):
    def __init__(self, con: sqlite3.Connection):
        self.__dict__["_con"] = con

    def __getattr__(self, item):
        return getattr(self._con, item)

    def execute(self, *a, **kw):
        for i in range(5):
            try:
                return self._con.execute(*a, **kw)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    time.sleep(0.05 * (i+1))
                    continue
                raise
        return self._con.execute(*a, **kw)
