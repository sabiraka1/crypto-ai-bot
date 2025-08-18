# src/crypto_ai_bot/core/storage/migrations/runner.py
import sqlite3
from pathlib import Path

def apply_all(con: sqlite3.Connection) -> None:
    """
    Находит *.sql миграции в versions/ и применяет их по возрастанию имени файла.
    """
    versions = sorted((Path(__file__).parent / "versions").glob("*.sql"))
    with con:
        for path in versions:
            sql = path.read_text(encoding="utf-8")
            con.executescript(sql)
