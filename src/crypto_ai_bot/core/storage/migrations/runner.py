from __future__ import annotations

import os
import re
import sqlite3
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    from ....utils.logging import get_logger  # type: ignore
except Exception:  # fallback на stdlib
    import logging
    def get_logger(name: str):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)

_log = get_logger("migrations.runner")

ALLOWED_COMMANDS = {
    "CREATE", "ALTER", "INSERT", "UPDATE", "DELETE",  # строго согласно политике безопасности
}

SQL_DIR_CANDIDATES: List[Path] = [
    Path(__file__).with_suffix("").parent / "sql",              # src/crypto_ai_bot/core/storage/migrations/sql
    Path("migrations/sql"),                                      # относительный путь (на всякий случай)
]

@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str
    checksum: str


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at INTEGER,
                dirty INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_lock (
                id INTEGER PRIMARY KEY CHECK (id=1),
                owner TEXT,
                locked_at INTEGER
            )
            """
        )
    except Exception:
        # В очень старых БД могла быть другая форма — пробуем мигрировать мета-таблицу мягко
        pass


def _hash_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _discover_sql_files() -> List[Path]:
    for base in SQL_DIR_CANDIDATES:
        if base.exists() and base.is_dir():
            files = sorted(p for p in base.glob("*.sql"))
            if files:
                return files
    return []


def _parse_version_name(path: Path) -> Tuple[str, str]:
    # Форматы: 001_init.sql, 20240820_add_orders.sql — всё до первого '_'/'-' считаем версией
    stem = path.stem
    m = re.match(r"^([0-9A-Za-z]+)[_-](.*)$", stem)
    if m:
        return m.group(1), m.group(2)
    return stem, stem


def _split_statements(sql: str) -> List[str]:
    # Простой, но безопасный splitter: по ';' вне строк
    statements: List[str] = []
    buff: List[str] = []
    in_str = False
    quote = ''
    for ch in sql:
        if ch in ('"', "'"):
            if not in_str:
                in_str = True; quote = ch
            elif quote == ch:
                in_str = False
        if ch == ';' and not in_str:
            stmt = ''.join(buff).strip()
            if stmt:
                statements.append(stmt)
            buff = []
        else:
            buff.append(ch)
    tail = ''.join(buff).strip()
    if tail:
        statements.append(tail)
    return statements


def _command_allowed(stmt: str) -> bool:
    # Берём первый токен (DDL/DML)
    first = re.split(r"\s+", stmt.strip(), maxsplit=1)[0].upper()
    # CREATE INDEX/VIEW/UNIQUE → начинаются с CREATE, whitelist покрывает
    return first in ALLOWED_COMMANDS


def _load_migrations_from_fs() -> List[Migration]:
    files = _discover_sql_files()
    migs: List[Migration] = []
    for p in files:
        sql = p.read_text(encoding="utf-8")
        ver, name = _parse_version_name(p)
        migs.append(Migration(version=ver, name=name, sql=sql, checksum=_hash_sql(sql)))
    return migs


def _load_applied(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT version, checksum, dirty FROM schema_migrations").fetchall()
    return {str(r[0]): {"checksum": str(r[1]), "dirty": int(r[2])} for r in rows}


def _apply_migration(conn: sqlite3.Connection, m: Migration, now_ms: int) -> None:
    # Отмечаем dirty и готовим транзакцию
    conn.execute("BEGIN IMMEDIATE;")  # single-writer
    try:
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, name, checksum, applied_at, dirty) VALUES(?,?,?,?,?)",
            (m.version, m.name, m.checksum, None, 1),
        )
        for stmt in _split_statements(m.sql):
            if not _command_allowed(stmt):
                raise RuntimeError(f"Forbidden SQL command in migration {m.version}: {stmt[:40]}...")
            conn.execute(stmt)
        conn.execute(
            "UPDATE schema_migrations SET applied_at=?, dirty=0 WHERE version=?",
            (now_ms, m.version),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def run_migrations(conn: sqlite3.Connection, *, now_ms: int) -> None:
    """Основная точка входа (сигнатура совместима с compose).

    Стратегия:
      1) Ensure meta + lock-совместимость (BEGIN IMMEDIATE).
      2) Загружаем список миграций из FS (если есть). Если нет — считаем, что нечего применять.
      3) Проверяем checksum изменённых исторических миграций → fail-fast.
      4) Применяем только отсутствующие версии, строго по порядку имён файлов.
    """
    _ensure_meta(conn)

    available = _load_migrations_from_fs()
    if not available:
        _log.info("no_migrations_found")
        return

    applied = _load_applied(conn)

    # Проверка изменённых исторических миграций
    for m in available:
        if m.version in applied:
            rec = applied[m.version]
            if int(rec.get("dirty", 0)) == 1:
                raise RuntimeError(
                    f"schema_migrations is dirty at version {m.version}. Run migrate_repair first."
                )
            old = rec.get("checksum")
            if old and old != m.checksum:
                raise RuntimeError(
                    f"checksum mismatch for version {m.version}: expected {old}, got {m.checksum}"
                )

    # Применяем только новые
    pending = [m for m in available if m.version not in applied]
    for m in pending:
        _log.info("apply_migration", extra={"version": m.version, "name": m.name})
        _apply_migration(conn, m, now_ms)
    _log.info("migrations_done", extra={"applied": len(pending)})