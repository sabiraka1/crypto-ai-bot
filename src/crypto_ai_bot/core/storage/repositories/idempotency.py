from __future__ import annotations

import sqlite3
from typing import Optional, Tuple, Any, Dict
from datetime import datetime, timezone
import json
import hashlib

class IdempotencyRepository:
    """
    Совместимая с нашей спецификацией реализация идемпотентности.
    Таблица ожидается как минимум с колонками:
      key TEXT PRIMARY KEY,
      payload_json TEXT,
      created_at_ms INTEGER,
      committed INTEGER DEFAULT 0,
      order_json TEXT NULL  -- если нет, будет graceful fallback
    (названия могут отличаться — используем best-effort UPSERT и try/except)

    API:
      - build_key(symbol, side, size, decision_id, *, ts_ms=None) -> str
      - check_and_store(key, payload) -> (is_new: bool, stored_payload: dict|str)
      - claim(key, payload) -> bool                    (alias для check_and_store()[0])
      - commit(key, original_order) -> None            (фиксирует исходный ордер)
      - release(key) -> None                           (по необходимости — очистка)
      - get_original_order(key) -> dict|None
    """

    def __init__(self, conn: sqlite3.Connection, table: str = "idempotency"):
        self._con = conn
        self._table = table

    # ---------- helpers ----------
    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    @staticmethod
    def build_key(symbol: str, side: str, size: str, decision_id: str, *, ts_ms: Optional[int] = None) -> str:
        """
        Спецификация ключа:
          {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
        timestamp_minute = floor((ts_ms or now)/60000)
        """
        if ts_ms is None:
            ts_ms = IdempotencyRepository._now_ms()
        minute = int(ts_ms // 60000)
        return f"{symbol}:{side}:{size}:{minute}:{(decision_id or '')[:8]}"

    @staticmethod
    def _to_json(payload: Any) -> str:
        if isinstance(payload, str):
            return json.dumps({"message": payload}, ensure_ascii=False)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"raw": str(payload)}, ensure_ascii=False)

    @staticmethod
    def _from_json(s: Optional[str]) -> Any:
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return {"raw": s}

    # ---------- API ----------
    def check_and_store(self, key: str, payload: Any) -> Tuple[bool, Any]:
        """
        Пытается вставить запись с ключом. Если уже есть — возвращает (False, старый payload).
        Если нет — вставляет и возвращает (True, текущий payload).
        """
        data = self._to_json(payload)
        try:
            self._con.execute(
                f"""INSERT INTO {self._table} (key, payload_json, created_at_ms, committed)
                    VALUES (?, ?, ?, 0)""",
                (key, data, self._now_ms()),
            )
            self._con.commit()
            return True, payload
        except Exception:
            # запись существует — вернуть старую
            try:
                cur = self._con.execute(f"SELECT payload_json FROM {self._table} WHERE key = ?", (key,))
                row = cur.fetchone()
                old = self._from_json(row[0]) if row else None
                return False, old
            except Exception:
                return False, None

    def claim(self, key: str, payload: Any) -> bool:
        is_new, _ = self.check_and_store(key, payload)
        return is_new

    def commit(self, key: str, original_order: Any) -> None:
        """Помечает как зафиксированную и пытается сохранить оригинальный ордер (order_json)."""
        try:
            order_json = self._to_json(original_order)
            # пытаемся обновить committed и order_json (если колонки нет — обновим только committed)
            try:
                self._con.execute(
                    f"UPDATE {self._table} SET committed = 1, order_json = ? WHERE key = ?",
                    (order_json, key),
                )
            except Exception:
                self._con.execute(
                    f"UPDATE {self._table} SET committed = 1 WHERE key = ?",
                    (key,),
                )
            self._con.commit()
        except Exception:
            try:
                self._con.rollback()
            except Exception:
                pass

    def release(self, key: str) -> None:
        """Опциональная очистка записи (в большинстве случаев можно оставить запись для истории)."""
        # По умолчанию ничего не делаем, но поддержим мягкое удаление:
        try:
            self._con.execute(f"DELETE FROM {self._table} WHERE key = ?", (key,))
            self._con.commit()
        except Exception:
            try:
                self._con.rollback()
            except Exception:
                pass

    def get_original_order(self, key: str) -> Optional[Dict]:
        """Возвращает ранее сохранённый ордер, если таблица поддерживает колонку order_json."""
        try:
            cur = self._con.execute(f"SELECT order_json FROM {self._table} WHERE key = ?", (key,))
            row = cur.fetchone()
            return self._from_json(row[0]) if row and row[0] else None
        except Exception:
            return None
