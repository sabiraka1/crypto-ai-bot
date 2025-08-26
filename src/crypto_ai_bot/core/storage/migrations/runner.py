from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# --- настройки -----------------------------------------------------------------
_ALLOWED_PREFIXES = (
    "create table",
    "create unique index",
    "create index",
    "alter table",   # проверим дальше, что только ADD COLUMN
    "insert into",
    "update",
    "delete from",
)
_FORBIDDEN_TOKENS = (
    "drop table",
    "drop view",
    "attach ",
    "detach ",
    "vacuum",
)

_SQL_DIR_NAME = "sql"


@dataclass
class Migration:
    version: str
    file: Path
    sql: str
    checksum: str


def _strip_comments(sql: str) -> str:
    # удаляем /* ... */ и -- до конца строки
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    return sql


def _split_statements(sql: str) -> List[str]:
    # безопасное разделение по ';' вне строк
    out: List[str] = []
    buff: List[str] = []
    in_s = False
    in_d = False
    esc = False
    for ch in sql:
        if ch == "'" and not in_d and not esc:
            in_s = not in_s
        elif ch == '"' and not in_s and not esc:
            in_d = not in_d
        if ch == ";" and not in_s and not in_d:
            stmt = "".join(buff).strip()
            if stmt:
                out.append(stmt)
            buff = []
        else:
            buff.append(ch)
        esc = (ch == "\\") and not esc
    tail = "".join(buff).strip()
    if tail:
        out.append(tail)
    return out


def _is_safe_alter(stmt_l: str) -> bool:
    # разрешаем только: ALTER TABLE <name> ADD COLUMN <name> <type> [DEFAULT ...]
    return bool(re.match(r"^alter\s+table\s+[^\s]+\s+add\s+column\s+.+", stmt_l))


def _validate_statement(stmt: str) -> None:
    s = stmt.strip()
    if not s:
        return
    s_l = s.lower()
    for bad in _FORBIDDEN_TOKENS:
        if bad in s_l:
            raise ValueError(f"Forbidden SQL token in migration: {bad}")
    if s_l.startswith("pragma") or s_l.startswith("begin") or s_l.startswith("commit") or s_l.startswith("rollback"):
        raise ValueError("PRAGMA/transaction statements are not allowed in migrations; managed by runner")
    if not any(s_l.startswith(pfx) for pfx in _ALLOWED_PREFIXES):
        raise ValueError(f"Statement not allowed by whitelist: {s.split(maxsplit=3)[:3]}")
    if s_l.startswith("alter table") and not _is_safe_alter(s_l):
        raise ValueError("Only ALTER TABLE ... ADD COLUMN is allowed")


def _normalize(sql: str) -> str:
    # нормализация для checksum
    return re.sub(r"\s+", " ", _strip_comments(sql)).strip()


def _checksum(sql: str) -> str:
    return hashlib.sha256(_normalize(sql).encode("utf-8")).hexdigest()


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at_ms INTEGER NOT NULL,
            dirty INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _set_pragmas(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass


def _load_migrations(dir_path: Path) -> List[Migration]:
    if not dir_path.exists():
        return []
    files = sorted(
        [p for p in dir_path.iterdir() if p.is_file() and p.name.lower().endswith(".sql")],
        key=lambda p: p.name,
    )
    out: List[Migration] = []
    for f in files:
        m = re.match(r"^V(\d{4,})__.+\.sql$", f.name)
        if not m:
            continue
        raw = f.read_text(encoding="utf-8")
        sql = raw.lstrip("\ufeff")  # уберём BOM при наличии
        out.append(Migration(version=m.group(1), file=f, sql=sql, checksum=_checksum(sql)))
    return out


def _already_applied(conn: sqlite3.Connection, version: str) -> Optional[Tuple[str, int, int]]:
    row = conn.execute("SELECT checksum, applied_at_ms, dirty FROM schema_migrations WHERE version=?", (version,)).fetchone()
    if row:
        return str(row[0]), int(row[1]), int(row[2])
    return None


def _apply_migration(conn: sqlite3.Connection, m: Migration, *, now_ms: int) -> None:
    # валидируем и исполняем атомарно под savepoint
    sql_wo_comments = _strip_comments(m.sql)
    statements = _split_statements(sql_wo_comments)
    for st in statements:
        _validate_statement(st)

    sp = f"migr_{m.version}"
    conn.execute(f"SAVEPOINT {sp}")
    try:
        for st in statements:
            conn.execute(st)
        conn.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at_ms, dirty) VALUES (?, ?, ?, 0)",
            (m.version, m.checksum, now_ms),
        )
        conn.execute(f"RELEASE SAVEPOINT {sp}")
    except Exception as exc:
        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        # помечаем как dirty (для сигнализации, что миграция падала)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, checksum, applied_at_ms, dirty) VALUES (?, ?, ?, 1)",
                (m.version, m.checksum, now_ms),
            )
        except Exception:
            pass
        raise


def run_migrations(conn: sqlite3.Connection, *, now_ms: int, migrations_dir: Optional[Path] = None) -> None:
    """Запускает миграции из каталога sql/ по whitelist‑правилам, атомарно и с checksum‑контролем.

    - запрещены опасные SQL (DROP TABLE/VIEW, PRAGMA, транзакции и т.п.)
    - ALTER TABLE разрешён только для ADD COLUMN
    - все миграции выполняются под savepoint; на сбое откатываются
    - если уже применённая версия имеет другой checksum — поднимаем исключение
    """
    _set_pragmas(conn)
    _ensure_meta(conn)

    base_dir = migrations_dir or (Path(__file__).resolve().parent / _SQL_DIR_NAME)
    migrations = _load_migrations(base_dir)

    for m in migrations:
        applied = _already_applied(conn, m.version)
        if applied:
            old_checksum, _applied_at, dirty = applied
            if old_checksum != m.checksum:
                raise RuntimeError(
                    f"Checksum mismatch for migration V{m.version} ({m.file.name}). "
                    f"Recorded={old_checksum}, Actual={m.checksum}. Manual intervention required."
                )
            # уже применена — пропускаем
            continue
        _apply_migration(conn, m, now_ms=now_ms)