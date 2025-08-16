# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics

# Опционально: зачистка протухших ключей идемпотентности во время обслуживания
try:
    from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepositorySQLite
except Exception:
    IdempotencyRepositorySQLite = None  # type: ignore


# ---------------------------------------------------------------------------
# Подключение к SQLite с безопасными для продакшена PRAGMA
# ---------------------------------------------------------------------------

def connect(db_path: str) -> sqlite3.Connection:
    """
    Создаёт соединение SQLite c WAL, busy_timeout, foreign_keys и адекватными настройками.
    Возвращает ОДНО соединение (thread-safe через check_same_thread=False).
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(
        db_path,
        isolation_level=None,         # управляем транзакциями сами (BEGIN ... COMMIT)
        check_same_thread=False,      # будем вызывать из рабочих потоков
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    con.row_factory = sqlite3.Row

    # Базовые PRAGMA. Выполняем вне транзакции.
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")        # WAL для конкурентности чтения/записи
    cur.execute("PRAGMA synchronous=NORMAL;")      # разумный баланс надёжности/скорости
    cur.execute("PRAGMA foreign_keys=ON;")         # внешние ключи
    cur.execute("PRAGMA temp_store=MEMORY;")       # временные структуры в памяти
    cur.execute("PRAGMA cache_size=-20000;")       # ~20MB кэша страниц (отрицательное = KB)
    cur.execute("PRAGMA busy_timeout=5000;")       # ждать до 5с при блокировке
    con.commit()
    return con


@contextmanager
def in_txn(con: sqlite3.Connection):
    """
    Контекст транзакции с BEGIN IMMEDIATE (блокируем запись, читающие не мешают).
    Безопасно откатывает при исключениях.
    """
    cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE;")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


# ---------------------------------------------------------------------------
# Метрики/статистика SQLite
# ---------------------------------------------------------------------------

def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def get_db_stats(con: sqlite3.Connection, *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Собирает ключевые статистики для мониторинга:
      - размер файла БД / WAL / SHM
      - page_count, page_size, freelist_count → оценка занятых/свободных байт
    Возвращает dict-структуру (готов к JSON).
    """
    cur = con.cursor()
    page_size = cur.execute("PRAGMA page_size;").fetchone()[0]
    page_count = cur.execute("PRAGMA page_count;").fetchone()[0]
    freelist_count = cur.execute("PRAGMA freelist_count;").fetchone()[0]

    used_pages = max(0, int(page_count) - int(freelist_count))
    used_bytes = int(page_size) * used_pages
    free_bytes = int(page_size) * int(freelist_count)

    # размеры файлов (если известен путь)
    db = db_path or getattr(con, "database", None) or ""
    wal = f"{db}-wal" if db else ""
    shm = f"{db}-shm" if db else ""

    db_bytes = _file_size(db) if db else 0
    wal_bytes = _file_size(wal) if wal else 0
    shm_bytes = _file_size(shm) if shm else 0

    # метрики как gauge-подобные observe
    metrics.observe("db_file_size_bytes", float(db_bytes), {"file": "main"})
    metrics.observe("db_file_size_bytes", float(wal_bytes), {"file": "wal"})
    metrics.observe("db_file_size_bytes", float(shm_bytes), {"file": "shm"})
    metrics.observe("db_page_size_bytes", float(page_size), {})
    metrics.observe("db_pages_total", float(page_count), {})
    metrics.observe("db_pages_free", float(freelist_count), {})
    metrics.observe("db_bytes_used", float(used_bytes), {})
    metrics.observe("db_bytes_free", float(free_bytes), {})

    return {
        "file": {
            "db_path": db,
            "db_bytes": db_bytes,
            "wal_bytes": wal_bytes,
            "shm_bytes": shm_bytes,
        },
        "pages": {
            "page_size": int(page_size),
            "page_count": int(page_count),
            "freelist_count": int(freelist_count),
            "used_bytes_est": int(used_bytes),
            "free_bytes_est": int(free_bytes),
        },
    }


def vacuum_analyze(con: sqlite3.Connection) -> Dict[str, Any]:
    """
    Выполняет VACUUM и ANALYZE (вне транзакции).
    Возвращает длительности операций.
    ВНИМАНИЕ: VACUUM требует эксклюзивного владения БД — запускай в окне низкой нагрузки.
    """
    # Заворачиваем в безопасные COMMIT-пункты
    t0 = time.perf_counter()
    cur = con.cursor()
    cur.execute("PRAGMA optimize;")  # дешёвое улучшение планов
    con.commit()

    t_vac0 = time.perf_counter()
    cur.execute("VACUUM;")
    con.commit()
    t_vac = time.perf_counter() - t_vac0

    t_an0 = time.perf_counter()
    cur.execute("ANALYZE;")
    con.commit()
    t_an = time.perf_counter() - t_an0

    total = time.perf_counter() - t0

    metrics.inc("db_vacuum_total", {})
    metrics.observe("db_vacuum_seconds", t_vac, {})
    metrics.observe("db_analyze_seconds", t_an, {})
    metrics.observe("db_maintenance_seconds", total, {})

    return {"vacuum_seconds": round(t_vac, 6), "analyze_seconds": round(t_an, 6), "total_seconds": round(total, 6)}


# ---------------------------------------------------------------------------
# Плановое обслуживание (интеграция с Orchestrator)
# ---------------------------------------------------------------------------

@dataclass
class _MaintConfig:
    every_hours: float = 6.0
    purge_idempotency: bool = True
    idem_ttl_seconds: int = 3600


def schedule_maintenance(orchestrator, *, db_path: str, every_hours: float = 6.0, purge_idempotency: bool = True, idem_ttl_seconds: int = 3600) -> None:
    """
    Регистрирует периодическую задачу в твоём Orchestrator (ожидается API schedule_every()).
    Делает:
      - get_db_stats()
      - (опц.) purge_expired() для идемпотентности
      - VACUUM/ANALYZE
      - повторный get_db_stats()
    """
    cfg = _MaintConfig(every_hours=every_hours, purge_idempotency=purge_idempotency, idem_ttl_seconds=idem_ttl_seconds)

    def _job():
        con = connect(db_path)
        try:
            before = get_db_stats(con, db_path=db_path)

            purged = None
            if purge_idempotency and IdempotencyRepositorySQLite is not None:
                try:
                    idem = IdempotencyRepositorySQLite(con)
                    purged = idem.purge_expired()
                    metrics.inc("db_idempotency_purged_total", {"count": str(purged)})
                except Exception:
                    # не фатально
                    purged = -1

            maint = vacuum_analyze(con)
            after = get_db_stats(con, db_path=db_path)

            metrics.observe("db_maintenance_db_bytes_after", float(after["file"]["db_bytes"]), {})
            metrics.observe("db_maintenance_free_bytes_after", float(after["pages"]["free_bytes_est"]), {})

            return {
                "before": before,
                "after": after,
                "maintenance": maint,
                "idempotency_purged": purged,
            }
        finally:
            try:
                con.close()
            except Exception:
                pass

    # 6 часов по умолчанию (в секундах). Добавляем небольшой jitter.
    seconds = max(60.0, float(cfg.every_hours) * 3600.0)
    orchestrator.schedule_every(int(seconds), _job, jitter=0.15)
