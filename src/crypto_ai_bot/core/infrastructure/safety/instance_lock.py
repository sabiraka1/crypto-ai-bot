from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import sys
import time
from typing import Optional

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("safety.lock")


@dataclass(slots=True)
class InstanceLock:
    """
    Межпроцессный лок поверх SQLite.
    Таблица app_locks(app PRIMARY KEY, owner, expire_at).
    Захват: UPSERT только если запись устарела (expire_at < now).
    """
    conn: sqlite3.Connection
    app: str
    owner: str

    def acquire(self, ttl_sec: int = 300) -> bool:
        """
        Пытаемся установить эксклюзивный лок.
        Возвращает True, если лок у нас; False, если держит другой процесс.
        """
        expire_at = int(time.time()) + int(ttl_sec)

        with self.conn:  # транзакция + commit
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_locks (
                    app TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expire_at INTEGER NOT NULL
                )
                """
            )
            # Пытаемся занять лок или продлить его, только если предыдущий истёк
            self.conn.execute(
                """
                INSERT INTO app_locks(app, owner, expire_at)
                VALUES(?, ?, ?)
                ON CONFLICT(app) DO UPDATE SET
                    owner=excluded.owner,
                    expire_at=excluded.expire_at
                WHERE app_locks.expire_at < CAST(strftime('%s','now') AS INTEGER)
                """,
                (self.app, self.owner, expire_at),
            )
            row = self.conn.execute(
                "SELECT owner, expire_at FROM app_locks WHERE app=?",
                (self.app,),
            ).fetchone()

        ok = bool(row and row[0] == self.owner)
        _log.info("lock_acquire", extra={"ok": ok, "owner": self.owner})
        return ok

    def renew(self, ttl_sec: int = 300) -> bool:
        """
        Продлевает лок, только если он у нас. Возвращает True при успехе.
        """
        expire_at = int(time.time()) + int(ttl_sec)
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE app_locks
                   SET expire_at=?
                 WHERE app=? AND owner=?
                """,
                (expire_at, self.app, self.owner),
            )
        ok = cur.rowcount == 1
        _log.info("lock_renew", extra={"ok": ok, "owner": self.owner})
        return ok

    def release(self) -> None:
        """Снимает лок, если он у нас."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM app_locks WHERE app=? AND owner=?",
                (self.app, self.owner),
            )
        _log.info("lock_release", extra={"owner": self.owner})

    def close(self) -> None:
        """Закрыть соединение с БД (после release)."""
        try:
            self.conn.close()
        except Exception:
            _log.error("lock_close_failed", exc_info=True)

    # Контекстный менеджер, чтобы удобно использовать в with ...
    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        with contextlib.suppress(Exception):
            self.release()
        with contextlib.suppress(Exception):
            self.close()


def create_instance_lock(app: str, owner: str, path: str = "instance.lock.db") -> InstanceLock:
    """
    Создаёт подключение к SQLite и пытается захватить лок.
    При неуспехе завершает процесс статусом 1.
    """
    # timeout — системный; busy_timeout — на уровне SQLite, помогает при гонках
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    # Немного здравых дефолтов для конкурентного доступа
    with conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")  # мс

    lock = InstanceLock(conn, app, owner)
    if not lock.acquire():
        _log.error("Another instance is already running", extra={"app": app, "owner": owner})
        raise SystemExit(1)  # эквивалент sys.exit(1), но явнее

    return lock


# Локальный импорт для __exit__
import contextlib  # noqa: E402
