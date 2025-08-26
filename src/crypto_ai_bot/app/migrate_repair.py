from __future__ import annotations

import argparse
import sqlite3
from typing import List, Dict, Any

from ..core.settings import Settings


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def _read_schema_migrations(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not _table_exists(conn, "schema_migrations"):
        return []
    cols = _columns(conn, "schema_migrations")
    cur = conn.execute("SELECT * FROM schema_migrations ORDER BY 1 ASC")
    rows = []
    for r in cur.fetchall():
        row = {c: r[c] if c in r.keys() else None for c in cols}
        rows.append(row)
    return rows


def cmd_show(conn: sqlite3.Connection) -> int:
    rows = _read_schema_migrations(conn)
    if not rows:
        print("schema_migrations: <empty or missing>")
        return 0
    print("schema_migrations:")
    for r in rows:
        print(" - ", {k: r.get(k) for k in r.keys()})
    return 0


def cmd_clear_dirty(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_migrations"):
        print("no schema_migrations table")
        return 1
    cols = set(_columns(conn, "schema_migrations"))
    if "dirty" not in cols:
        print("no 'dirty' column — nothing to clear")
        return 0
    conn.execute("UPDATE schema_migrations SET dirty=0 WHERE dirty<>0")
    conn.commit()
    print("dirty cleared")
    return 0


def cmd_delete_version(conn: sqlite3.Connection, version: str) -> int:
    if not _table_exists(conn, "schema_migrations"):
        print("no schema_migrations table")
        return 1
    conn.execute("DELETE FROM schema_migrations WHERE version=? OR name=?", (version, version))
    conn.commit()
    print(f"deleted migration entry: {version}")
    return 0


def cmd_vacuum(conn: sqlite3.Connection) -> int:
    conn.execute("VACUUM")
    print("vacuum done")
    return 0


def main() -> int:
    settings = Settings.load()
    conn = _connect(settings.DB_PATH)

    p = argparse.ArgumentParser(description="Repair tool for schema_migrations")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show", help="print table content")
    sub.add_parser("clear-dirty", help="set dirty=0 for all rows")

    d = sub.add_parser("delete", help="delete row by version or name")
    d.add_argument("version", help="version or name")

    sub.add_parser("vacuum", help="VACUUM database")

    args = p.parse_args()

    if args.cmd == "show":
        return cmd_show(conn)
    if args.cmd == "clear-dirty":
        return cmd_clear_dirty(conn)
    if args.cmd == "delete":
        return cmd_delete_version(conn, args.version)
    if args.cmd == "vacuum":
        return cmd_vacuum(conn)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())