from __future__ import annotations
import sqlite3
from typing import Iterable, Tuple

# 1) пакет ресурсов = сам пакет 'crypto_ai_bot.core.storage.migrations'
import importlib.resources as pkg_resources
import crypto_ai_bot.core.storage.migrations as _pkg  # ← это и есть пакет с .sql файлами


def _ensure_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at_ms INTEGER NOT NULL
        );
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def _apply(conn: sqlite3.Connection, version: str, sql: str, now_ms: int) -> None:
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO schema_migrations(version, applied_at_ms) VALUES (?, ?)",
        (version, now_ms),
    )


def discover_migrations() -> Iterable[Tuple[str, str]]:
    """
    Ищет *.sql внутри пакета crypto_ai_bot.core.storage.migrations и
    отдаёт (version, sql), отсортированные по имени файла.
    """
    entries: list[tuple[str, str]] = []

    # Основной путь: importlib.resources (работает и из sdist/zip)
    try:
        for res in pkg_resources.files(_pkg).iterdir():
            name = res.name
            if res.is_file() and name.endswith(".sql"):
                sql = res.read_text(encoding="utf-8")
                entries.append((name, sql))
    except Exception:
        # Фолбэк на файловую систему (на случай старых Python/окружений)
        import pathlib
        pkg_dir = pathlib.Path(__file__).parent
        for p in pkg_dir.glob("*.sql"):
            entries.append((p.name, p.read_text(encoding="utf-8")))

    entries.sort(key=lambda t: t[0])
    return [(n.rsplit(".", 1)[0], sql) for (n, sql) in entries]


def run_migrations(conn: sqlite3.Connection, *, now_ms: int) -> list[str]:
    """Применяет все неустановленные миграции. Возвращает список применённых версий."""
    _ensure_schema_table(conn)
    applied = _applied_versions(conn)
    applied_now: list[str] = []
    for version, sql in discover_migrations():
        if version in applied:
            continue
        with conn:
            _apply(conn, version, sql, now_ms)
        applied_now.append(version)
    return applied_now
