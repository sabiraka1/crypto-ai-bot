from __future__ import annotations

import sqlite3
from typing import Optional

from crypto_ai_bot.utils.time import now_ms


class IdempotencyRepository:
    """
    Минимальный репозиторий идемпотентности.
    
    Использует упрощенную схему:
    - idempotency(key TEXT PRIMARY KEY, ts_ms INTEGER, ttl_sec INTEGER)
    
    Семантика:
    - Удаляем протухшие записи по ttl_sec
    - Пытаемся вставить новую; при конфликте key → считаем дубликатом
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # Создаем таблицу если не существует
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                ts_ms INTEGER NOT NULL,
                ttl_sec INTEGER NOT NULL
            )
        """)
        self._conn.commit()

    def check_and_store(self, key: str, ttl_sec: int, default_bucket_ms: int = 60000) -> bool:
        """
        Проверяет и сохраняет ключ идемпотентности.
        
        Args:
            key: Уникальный ключ идемпотентности
            ttl_sec: Время жизни ключа в секундах
            default_bucket_ms: Размер временного окна в миллисекундах (для совместимости)
        
        Returns:
            True если ключ успешно сохранен (не было активной записи)
            False если такой ключ уже существует и еще не истек
        """
        cur = self._conn.cursor()
        now = now_ms()
        
        # Очистка протухших записей
        # Удаляем записи где прошло больше ttl_sec секунд с момента создания
        cur.execute(
            "DELETE FROM idempotency WHERE (? - ts_ms) > (ttl_sec * 1000)", 
            (now,)
        )
        
        # Попытка вставки новой записи
        try:
            cur.execute(
                "INSERT INTO idempotency(key, ts_ms, ttl_sec) VALUES (?, ?, ?)", 
                (key, now, ttl_sec)
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Ключ уже существует и еще активен
            self._conn.rollback()
            return False
        except Exception:
            # Любая другая ошибка также считается дубликатом
            self._conn.rollback()
            return False

    def next_client_order_id(self, exchange: str, tag: str, *, bucket_ms: int) -> str:
        """
        Генерирует следующий уникальный client_order_id на основе временного окна.
        
        Args:
            exchange: Название биржи
            tag: Тег для идентификации (например, символ и действие)
            bucket_ms: Размер временного окна в миллисекундах
        
        Returns:
            Уникальный идентификатор ордера
        """
        bucket = (now_ms() // bucket_ms) * bucket_ms
        return f"{exchange}-{tag}-{bucket}"

    def prune_older_than(self, seconds: int = 604800) -> int:
        """
        Удаляет записи старше указанного количества секунд.
        
        Args:
            seconds: Количество секунд (по умолчанию 7 дней)
        
        Returns:
            Количество удаленных записей
        """
        cutoff = now_ms() - int(seconds) * 1000
        cur = self._conn.execute(
            "DELETE FROM idempotency WHERE ts_ms < ?", 
            (cutoff,)
        )
        self._conn.commit()
        return cur.rowcount or 0

    def clear_all(self) -> None:
        """Очищает все записи идемпотентности."""
        self._conn.execute("DELETE FROM idempotency")
        self._conn.commit()


# Алиас для обратной совместимости
IdempotencyRepo = IdempotencyRepository