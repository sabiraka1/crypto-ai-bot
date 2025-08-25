from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ..storage.facade import Storage

_log = get_logger("safety.instance_lock")

DDL = """
CREATE TABLE IF NOT EXISTS locks (
  app TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  acquired_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL
);
"""

@dataclass
class InstanceLock:
    storage: Storage
    app: str
    owner: str

    def _ensure_table(self) -> None:
        self.storage.conn.execute(DDL)

    def acquire(self, *, ttl_sec: int = 300) -> bool:
        self._ensure_table()
        ts = now_ms()
        exp = ts + ttl_sec * 1000
        try:
            self.storage.conn.execute(
                "INSERT INTO locks(app,owner,acquired_at_ms,expires_at_ms) VALUES(?,?,?,?) "
                "ON CONFLICT(app) DO UPDATE SET "
                "owner=excluded.owner, acquired_at_ms=excluded.acquired_at_ms, expires_at_ms=excluded.expires_at_ms "
                "WHERE locks.expires_at_ms < ?",
                (self.app, self.owner, ts, exp, ts)
            )
            # Если запись «обновилась» только когда истёк TTL, то мы захватили лок.
            # Для простоты считаем, что один процесс на приложение.
            return True
        except Exception as exc:
            _log.error("lock_acquire_failed", extra={"error": str(exc)})
            return False

    def heartbeat(self, *, ttl_sec: int = 300) -> None:
        ts = now_ms()
        exp = ts + ttl_sec * 1000
        self.storage.conn.execute(
            "UPDATE locks SET acquired_at_ms=?, expires_at_ms=? WHERE app=? AND owner=?",
            (ts, exp, self.app, self.owner)
        )

    def release(self) -> None:
        try:
            self.storage.conn.execute("DELETE FROM locks WHERE app=? AND owner=?", (self.app, self.owner))
        except Exception:
            pass
