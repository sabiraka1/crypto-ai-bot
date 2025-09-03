from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import time

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("safety.lock")


@dataclass
class InstanceLock:
    conn: sqlite3.Connection
    app: str
    owner: str

    def acquire(self, ttl_sec: int = 300) -> bool:
        """ДћЕёГ‘вЂ№Г‘вЂљДћВ°ДћВµДћВјГ‘ВЃГ‘ВЏ ДћВІДћВ·Г‘ВЏГ‘вЂљГ‘Е’ Г‘ВЌДћВєГ‘ВЃДћВєДћВ»Г‘ВЋДћВ·ДћВёДћВІДћВЅГ‘вЂ№ДћВ№ ДћВ»ДћВѕДћВє. ДћвЂ™ДћВѕДћВ·ДћВІГ‘в‚¬ДћВ°Г‘вЂ°ДћВ°ДћВµГ‘вЂљ True ДћВїГ‘в‚¬ДћВё Г‘Ж’Г‘ВЃДћВїДћВµГ‘вЂ¦ДћВµ.
        ДћВЎГ‘вЂ¦ДћВµДћВјДћВ°: Г‘вЂљДћВ°ДћВ±ДћВ»ДћВёГ‘вЂ ДћВ° app_locks(app TEXT PK, owner TEXT, expire_at INTEGER).
        """
        expire_at = int(time.time()) + int(ttl_sec)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_locks (
                app TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                expire_at INTEGER NOT NULL
            )
            """
        )
        # ДћВїДћВѕДћВїГ‘вЂ№Г‘вЂљДћВ°Г‘вЂљГ‘Е’Г‘ВЃГ‘ВЏ ДћВІГ‘ВЃГ‘вЂљДћВ°ДћВІДћВёГ‘вЂљГ‘Е’ ДћВ»ДћВѕДћВє, ДћВµГ‘ВЃДћВ»ДћВё ДћВµДћВіДћВѕ ДћВЅДћВµГ‘вЂљ ДћВёДћВ»ДћВё ДћВёГ‘ВЃГ‘вЂљГ‘вЂДћВє Гўв‚¬вЂќ ДћВ·ДћВ°Г‘вЂ¦ДћВІДћВ°Г‘вЂљДћВёГ‘вЂљГ‘Е’
        cur = self.conn.execute(
            """
            INSERT INTO app_locks(app, owner, expire_at)
            VALUES(?, ?, ?)
            ON CONFLICT(app) DO UPDATE SET
                owner=excluded.owner,
                expire_at=excluded.expire_at
            WHERE app_locks.expire_at < strftime('%s','now')
            """,
            (self.app, self.owner, expire_at),
        )
        # sqlite ДћВЅДћВµ ДћВґДћВ°Г‘вЂГ‘вЂљ rowcount ДћВїДћВѕ upsert Г‘Ж’Г‘ВЃДћВ»ДћВѕДћВІДћВЅДћВѕ; ДћВїДћВµГ‘в‚¬ДћВµДћВїГ‘в‚¬ДћВѕДћВІДћВµГ‘в‚¬Г‘Е’ ДћВІДћВ»ДћВ°ДћВґДћВµДћВЅДћВёДћВµ
        cur = self.conn.execute("SELECT owner, expire_at FROM app_locks WHERE app=?", (self.app,))
        row = cur.fetchone()
        ok = bool(row and row[0] == self.owner)
        _log.info("lock_acquire", extra={"ok": ok, "owner": self.owner})
        return ok

    def release(self) -> None:
        self.conn.execute("DELETE FROM app_locks WHERE app=? AND owner=?", (self.app, self.owner))
        _log.info("lock_release", extra={"owner": self.owner})
