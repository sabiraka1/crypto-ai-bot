from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Set, Optional

from ....utils.logging import get_logger

_LOG = get_logger("migrations")
_MIGR_TABLE = "__migrations__"


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_MIGR_TABLE} ("
        "  version TEXT PRIMARY KEY,"
        "  applied_at_ms INTEGER NOT NULL"
        ")"
    )
    conn.commit()


def _list_sql_files() -> List[Path]:
    d = Path(__file__).parent
    files = sorted([p for p in d.glob("*.sql")], key=lambda p: p.name)
    # Гарантируем порядок: 0001_init.sql первой
    files.sort(key=lambda p: (p.name != "0001_init.sql", p.name))
    return files


def _read_migrations() -> List[tuple[str, str]]:
    out: List[tuple[str, str]] = []
    for p in _list_sql_files():
        try:
            sql = p.read_text(encoding="utf-8")
        except Exception:
            sql = p.read_text()
        out.append((p.stem, sql))
    return out


def _applied_versions(conn: sqlite3.Connection) -> Set[str]:
    _ensure_meta(conn)
    rows = conn.execute(f"SELECT version FROM {_MIGR_TABLE}").fetchall()
    return {r[0] for r in rows}


def _iter_statements(sql: str) -> List[str]:
    """Делим по ';' и выкидываем транзакционные директивы — мы их НЕ исполняем."""
    stmts: List[str] = []
    for part in sql.split(";"):
        s = part.strip()
        if not s:
            continue
        u = s.upper()
        if u.startswith("BEGIN") or u.startswith("COMMIT") or u.startswith("END") or u.startswith("ROLLBACK"):
            continue
        stmts.append(s)
    return stmts


def _extract_index_table(stmt_upper: str) -> Optional[str]:
    """Парсим CREATE [UNIQUE] INDEX ... ON <table>( ... ) → возвращаем имя таблицы (lower)."""
    try:
        on_pos = stmt_upper.index(" ON ")
        after = stmt_upper[on_pos + 4 :]
        paren = after.index("(")
        table = after[:paren].strip()
        if "." in table:
            table = table.split(".")[-1]
        return table.lower()
    except Exception:
        return None


def _extract_create_table(stmt_upper: str) -> Optional[str]:
    """Парсим CREATE TABLE [IF NOT EXISTS] <table>( ... ) → имя таблицы (lower)."""
    if not stmt_upper.startswith("CREATE TABLE"):
        return None
    try:
        after_kw = stmt_upper[len("CREATE TABLE") :].strip()
        if after_kw.startswith("IF NOT EXISTS"):
            after_kw = after_kw[len("IF NOT EXISTS") :].strip()
        paren = after_kw.index("(")
        table = after_kw[:paren].strip()
        if "." in table:
            table = table.split(".")[-1]
        return table.lower()
    except Exception:
        return None


def _existing_tables(conn: sqlite3.Connection) -> Set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]).lower() for r in rows}


def _apply(conn: sqlite3.Connection, version: str, sql: str, now_ms: int) -> None:
    """
    Исполняем команды по очереди БЕЗ ручного BEGIN/COMMIT (никаких вложенных транзакций).
    - CREATE TABLE → выполняем и добавляем таблицу в set.
    - CREATE INDEX → выполняем ТОЛЬКО если целевая таблица существует (сравнение case-insensitive).
    - Остальные команды → просто выполняем.
    В конце помечаем миграцию применённой и делаем commit().
    """
    try:
        tables = _existing_tables(conn)

        for stmt in _iter_statements(sql):
            u = stmt.upper()

            if u.startswith("CREATE TABLE"):
                conn.execute(stmt)
                tbl = _extract_create_table(u)
                if tbl:
                    tables.add(tbl)
                continue

            if u.startswith("CREATE INDEX") or u.startswith("CREATE UNIQUE INDEX"):
                table = _extract_index_table(u)
                if table and table not in tables:
                    _LOG.info("skip_index_missing_table", extra={"version": version, "table": table})
                    continue

            conn.execute(stmt)

        conn.execute(
            f"INSERT INTO {_MIGR_TABLE}(version, applied_at_ms) VALUES (?, ?)",
            (version, int(now_ms)),
        )
        conn.commit()
        _LOG.info("migration_applied", extra={"version": version})
    except Exception as exc:
        conn.rollback()
        _LOG.error("migration_failed", extra={"version": version, "error": str(exc)})
        raise


def run_migrations(conn: sqlite3.Connection, *, now_ms: Optional[int] = None) -> None:
    """Применяет все *.sql миграции (0001_init → остальные).
       Индексы на отсутствующие таблицы безопасно пропускаются (регистронезависимо).
    """
    _ensure_meta(conn)
    applied = _applied_versions(conn)
    all_migrations = _read_migrations()
    to_apply = [(v, s) for (v, s) in all_migrations if v not in applied]

    for version, sql in to_apply:
        _apply(conn, version, sql, int(now_ms or 0))

    if to_apply:
        _LOG.info("migrations_applied", extra={"versions": [v for v, _ in to_apply]})
