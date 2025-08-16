from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple


class SqliteIdempotencyRepository:
    """
    Простейшая реализация идемпотентности поверх SQLite.
    Таблица:
      key TEXT PRIMARY KEY
      payload TEXT NULL         -- что пытались выполнить (решение и т.п.)
      result  TEXT NULL         -- итог операции (для повторной выдачи)
      created_ms INTEGER NOT NULL
      committed INTEGER NOT NULL DEFAULT 0
      updated_ms INTEGER NULL
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self._ensure_schema()

    # ---------- schema ----------
    def _ensure_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                payload TEXT NULL,
                result TEXT NULL,
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                updated_ms INTEGER NULL
            );
            """
        )
        # индексы под TTL/поиск
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms);")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_committed ON idempotency(committed);")

    # ---------- primitives ----------
    def purge_expired(self, ttl_seconds: int) -> int:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (threshold,))
            return cur.rowcount if cur.rowcount is not None else 0

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Пытаемся «захватить» ключ. Если он уже существует (и не истёк), вернём False.
        Перед вставкой чистим истёкшие записи.
        """
        self.purge_expired(ttl_seconds)
        now_ms = int(time.time() * 1000)
        try:
            with self.con:
                self.con.execute(
                    "INSERT INTO idempotency(key, created_ms, committed) VALUES (?, ?, 0)",
                    (key, now_ms),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def commit(self, key: str, result: Dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET result = ?, committed = 1, updated_ms = ? WHERE key = ?",
                (self._to_json(result), now_ms, key),
            )

    def release(self, key: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))

    def get_original(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.con.execute(
            "SELECT payload, result, committed, created_ms, updated_ms FROM idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        payload, result, committed, created_ms, updated_ms = row
        return {
            "payload": self._from_json(payload),
            "result": self._from_json(result),
            "committed": bool(committed),
            "created_ms": int(created_ms),
            "updated_ms": int(updated_ms) if updated_ms is not None else None,
        }

    # ---------- helpers ----------
    def check_and_store(self, key: str, payload_json: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Удобный метод для сценария "сначала захватить, потом записать входные данные".
        Возвращает (is_new, prev). Если запись уже существует в пределах TTL, вернёт prev.
        """
        if self.claim(key, ttl_seconds=ttl_seconds):
            # сохраним payload сразу, чтобы повтор мог вернуть его
            now_ms = int(time.time() * 1000)
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload = ?, updated_ms = ? WHERE key = ?",
                    (payload_json, now_ms, key),
                )
            return True, None
        else:
            return False, self.get_original(key)

    # простые текстовые сериализаторы (ожидается JSON-строка на вход)
    @staticmethod
    def _to_json(obj: Any) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, str):
            return obj
        # безопасно, без зависимостей
        import json
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _from_json(s: Any) -> Any:
        if s is None:
            return None
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8", "ignore")
        if isinstance(s, str):
            s = s.strip()
            if s == "null" or s == "":
                return None
            import json
            try:
                return json.loads(s)
            except Exception:
                return s
        return s
