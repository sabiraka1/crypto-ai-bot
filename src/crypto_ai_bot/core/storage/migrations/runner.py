from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import List, Tuple

_MIG_RE = re.compile(r"^(\d{4})_.*\.sql$", re.IGNORECASE)

def _versions_dir(default: Path | None = None) -> Path:
    if default is None:
        default = Path(__file__).with_name("versions")
    return default

def list_migration_files(versions_dir: str | os.PathLike | None = None) -> List[Tuple[int, Path]]:
    """Возвращает список (version_number, path), отсортированный по номеру."""
    vdir = Path(versions_dir) if versions_dir else _versions_dir()
    files: List[Tuple[int, Path]] = []
    if not vdir.exists():
        return files
    for p in vdir.iterdir():
        if not p.is_file():
            continue
        m = _MIG_RE.match(p.name)
        if not m:
            continue
        ver = int(m.group(1))
        files.append((ver, p))
    files.sort(key=lambda x: x[0])
    return files

def get_current_version(con: sqlite3.Connection) -> int:
    """Читает текущую версию схемы из таблицы schema_version (если есть)."""
    try:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if not cur.fetchone():
            return 0
        cur = con.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        if not row:
            return 0
        return int(row[0])
    except Exception:
        return 0

def pending_migrations_count(con: sqlite3.Connection, versions_dir: str | os.PathLike | None = None) -> int:
    """Считает количество неподтвержденных миграций (файлы с номером > current_version)."""
    current = get_current_version(con)
    files = list_migration_files(versions_dir)
    pending = [ver for (ver, _) in files if ver > current]
    return len(pending)

# Ниже опциональная функция применения всех миграций, если понадобится в будущих шагах.
def apply_all(con: sqlite3.Connection, versions_dir: str | os.PathLike | None = None) -> int:
    """Применяет все миграции строго по порядку. Возвращает количество примененных миграций.
    Требует наличия таблицы schema_version (создаёт при необходимости)."""
    files = list_migration_files(versions_dir)
    with con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );
        """)
        cur = con.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        current = int(row[0]) if row else 0
        applied = 0
        for ver, path in files:
            if ver <= current:
                continue
            sql = path.read_text(encoding="utf-8")
            con.executescript(sql)
            con.execute("DELETE FROM schema_version")
            con.execute("INSERT INTO schema_version(version) VALUES (?)", (ver,))
            current = ver
            applied += 1
        return applied
