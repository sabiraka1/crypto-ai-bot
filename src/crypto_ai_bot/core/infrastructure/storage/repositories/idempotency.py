from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


@dataclass
class IdempotencyRepository:
    """
    Простая таблица идемпотентности на SQLite:
      - check_and_store(key, ttl_sec) — атомарно проверяет «не видел ли» и записывает срок годности.
      - prune_older_than(seconds)     — удаляет протухшие записи.
    Таблица создаётся лениво (ensure_schema).
    """

    conn: Any
    _initialized: bool = False

    # ---------- schema ----------
    def ensure_schema(self) -> None:
        if self._initialized:
            return
        cur = self.conn.cursor()
        try:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS idempotency (  key TEXT PRIMARY KEY,  expire_at INTEGER NOT NULL)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_idem_expire ON idempotency(expire_at)")
            self.conn.commit()
            self._initialized = True
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass

    # ---------- api ----------
    def check_and_store(self, key: str, ttl_sec: int) -> bool:
        """
        Вернёт True, если ключ впервые увиден (и мы его записали);
        False — если запись уже была (или вставка проигнорирована).
        Реализовано как атомарная операция в одной транзакции.
        """
        if not key:
            return False

        self.ensure_schema()
        now = _now_ms()
        expire_at = now + int(max(0, ttl_sec) * 1000)

        cur = self.conn.cursor()
        try:
            # BEGIN IMMEDIATE гарантирует, что вставка/очистка выполнится атомарно,
            # не блокируя читателей.
            cur.execute("BEGIN IMMEDIATE")
            # чистим старые записи (по чуть-чуть; без тяжёлых VACUUM)
            cur.execute("DELETE FROM idempotency WHERE expire_at < ?", (now,))
            # пытаемся вставить новый ключ
            cur.execute(
                "INSERT OR IGNORE INTO idempotency(key, expire_at) VALUES(?, ?)",
                (key, expire_at),
            )
            inserted = cur.rowcount == 1
            self.conn.commit()
            return bool(inserted)
        except Exception:
            try:
                self.conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass

    def prune_older_than(self, seconds: int) -> None:
        """Удалить записи, срок годности которых истёк раньше, чем now - seconds."""
        self.ensure_schema()
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM idempotency WHERE expire_at < ?", (_now_ms() - max(0, seconds) * 1000,))
            self.conn.commit()
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass

    # ---------- возможные расширения (не ломают API) ----------
    def has(self, key: str) -> bool:
        """Проверить наличие ключа (без вставки). Удобно для диагностик/тестов."""
        self.ensure_schema()
        cur = self.conn.cursor()
        try:
            row = cur.execute("SELECT 1 FROM idempotency WHERE key = ? LIMIT 1", (key,)).fetchone()
            return bool(row)
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
