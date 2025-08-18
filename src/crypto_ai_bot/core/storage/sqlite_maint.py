from __future__ import annotations
import sqlite3, time
from typing import Any, Optional, Tuple
from crypto_ai_bot.utils.metrics import inc, gauge

META_DDL = """
CREATE TABLE IF NOT EXISTS maintenance_meta(
  key TEXT PRIMARY KEY,
  val_int INTEGER
);
"""

def _now_ms() -> int:
    return int(time.time() * 1000)

def _get_meta(con: sqlite3.Connection, key: str) -> Optional[int]:
    cur = con.execute("SELECT val_int FROM maintenance_meta WHERE key=?", (key,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _set_meta(con: sqlite3.Connection, key: str, val: int) -> None:
    with con:
        con.execute("INSERT INTO maintenance_meta(key,val_int) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET val_int=excluded.val_int", (key, int(val)))

# -------------------- PRAGMAS --------------------

def apply_connection_pragmas(con: sqlite3.Connection, settings: Any) -> None:
    """
    Аккуратно настраиваем SQLite. Всё идемпотентно и безопасно для Railway.
    """
    try:
        con.execute(META_DDL)

        if not bool(getattr(settings, "DB_PRAGMAS_ENABLE", True)):
            return

        # Таймаут ожидания блокировок
        busy_ms = int(getattr(settings, "DB_BUSY_TIMEOUT_MS", 5000))
        con.execute(f"PRAGMA busy_timeout = {busy_ms}")

        # WAL + нормальная синхронизация (баланс скорость/надёжность)
        jmode = str(getattr(settings, "DB_JOURNAL_MODE", "WAL"))
        try:
            con.execute(f"PRAGMA journal_mode = {jmode}")
        except Exception:
            pass  # на in-memory/readonly может не сработать

        sync = str(getattr(settings, "DB_SYNCHRONOUS", "NORMAL"))
        con.execute(f"PRAGMA synchronous = {sync}")

        # Кэш и temp в памяти
        cache_mb = int(getattr(settings, "DB_CACHE_MB", 64))
        con.execute(f"PRAGMA cache_size = {-max(1, cache_mb) * 1024}")  # отрицательное значение — КБ
        temp_store = str(getattr(settings, "DB_TEMP_STORE", "MEMORY")).upper()
        con.execute(f"PRAGMA temp_store = {temp_store}")

        # mmap и foreign keys
        mmap_mb = int(getattr(settings, "DB_MMAP_SIZE_MB", 64))
        con.execute(f"PRAGMA mmap_size = {max(0, mmap_mb) * 1024 * 1024}")
        con.execute("PRAGMA foreign_keys = ON")

        # WAL autocheckpoint (в страницах)
        wal_autock = int(getattr(settings, "DB_WAL_AUTOCHECKPOINT", 1000))
        con.execute(f"PRAGMA wal_autocheckpoint = {wal_autock}")

        inc("db_pragmas_applied", {})
    except Exception:
        # Никаких падений на старте — максимум теряем оптимизации
        inc("db_pragmas_failed", {})

# -------------------- MAINTENANCE --------------------

def _optimize(con: sqlite3.Connection) -> None:
    # pragma optimize может вернуть несколько строк — просто исполним
    try:
        list(con.execute("PRAGMA optimize"))
    except Exception:
        pass

def quick_maintenance(con: sqlite3.Connection) -> float:
    """
    Быстрое обслуживание без блокирующих операций:
      - PRAGMA optimize
      - ANALYZE при необходимости (редко)
      - wal_checkpoint(PASSIVE)
    """
    t0 = time.perf_counter()
    try:
        con.execute(META_DDL)
        _optimize(con)

        # раз в 12 часов — ANALYZE (лёгкая выборка; не VACUUM)
        now = _now_ms()
        last_an = _get_meta(con, "last_analyze_ms")
        if last_an is None or (now - last_an) >= 12 * 3600 * 1000:
            try:
                con.execute("ANALYZE")
                _set_meta(con, "last_analyze_ms", now)
                inc("db_analyze_runs", {})
            except Exception:
                inc("db_analyze_failed", {})

        # скинуть WAL при необходимости (не блокирующий PASSIVE)
        try:
            con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

        inc("db_quick_maint_runs", {})
    finally:
        dur = time.perf_counter() - t0
        gauge("db_maint_duration_seconds", dur, {"type": "quick"})
    return dur

def full_maintenance(con: sqlite3.Connection) -> float:
    """
    Полное обслуживание (тяжёлое): VACUUM + ANALYZE.
    НИКОГДА не вызывать часто. Желательно — вне пика нагрузки.
    """
    t0 = time.perf_counter()
    try:
        con.execute(META_DDL)
        # VACUUM нельзя внутри транзакции, autocommit включён — ок
        try:
            con.execute("VACUUM")
            inc("db_vacuum_runs", {})
        except Exception:
            inc("db_vacuum_failed", {})
        try:
            con.execute("ANALYZE")
            inc("db_analyze_runs", {})
        except Exception:
            inc("db_analyze_failed", {})

        _set_meta(con, "last_full_ms", _now_ms())
        inc("db_full_maint_runs", {})
    finally:
        dur = time.perf_counter() - t0
        gauge("db_maint_duration_seconds", dur, {"type": "full"})
    return dur

def run_scheduled_maintenance(con: sqlite3.Connection, settings: Any) -> Tuple[str, float]:
    """
    Решает, что запускать сейчас (quick/full) по интервалам из настроек.
    Возвращает (тип, длительность_сек).
    """
    try:
        con.execute(META_DDL)
    except Exception:
        return ("skip", 0.0)

    quick_sec = int(getattr(settings, "DB_MAINT_QUICK_SEC", 10 * 60))     # 10 минут
    full_sec  = int(getattr(settings, "DB_MAINT_FULL_SEC",  3 * 24 * 3600))  # 3 дня

    now = _now_ms()
    last_q = _get_meta(con, "last_quick_ms")
    last_f = _get_meta(con, "last_full_ms")

    # Full — если очень давно не делали
    if last_f is None or (now - last_f) >= full_sec * 1000:
        dur = full_maintenance(con)
        _set_meta(con, "last_quick_ms", now)  # чтобы счетчик quick не «перестрельнул» сразу же
        return ("full", dur)

    # Quick — по расписанию
    if last_q is None or (now - last_q) >= quick_sec * 1000:
        dur = quick_maintenance(con)
        _set_meta(con, "last_quick_ms", now)
        return ("quick", dur)

    return ("skip", 0.0)
