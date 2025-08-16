from __future__ import annotations
import sqlite3

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con
