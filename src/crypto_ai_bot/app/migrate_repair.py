from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from ..core.settings import Settings
from ..core.storage.migrations.runner import run_migrations

try:
    from ..utils.logging import get_logger  # type: ignore
except Exception:  # fallback
    import logging
    def get_logger(name: str):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)

_log = get_logger("migrate_repair")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def cmd_show(args: argparse.Namespace) -> int:
    s = Settings.load()
    conn = _connect(s.DB_PATH)
    try:
        cur = conn.execute("SELECT version, name, checksum, applied_at, dirty FROM schema_migrations ORDER BY version")
        rows = cur.fetchall()
        print("version\tdirty\tname")
        for r in rows:
            print(f"{r['version']}\t{r['dirty']}\t{r['name']}")
        if not rows:
            print("(empty)")
        return 0
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    finally:
        conn.close()


def cmd_clear_dirty(args: argparse.Namespace) -> int:
    s = Settings.load()
    conn = _connect(s.DB_PATH)
    try:
        conn.execute("UPDATE schema_migrations SET dirty=0 WHERE dirty=1")
        conn.commit()
        print("cleared dirty flags")
        return 0
    finally:
        conn.close()


def cmd_delete(args: argparse.Namespace) -> int:
    s = Settings.load()
    conn = _connect(s.DB_PATH)
    try:
        conn.execute("DELETE FROM schema_migrations WHERE version=?", (args.version,))
        conn.commit()
        print(f"deleted version {args.version}")
        return 0
    finally:
        conn.close()


def cmd_vacuum(args: argparse.Namespace) -> int:
    s = Settings.load()
    conn = _connect(s.DB_PATH)
    try:
        conn.execute("VACUUM")
        print("vacuum done")
        return 0
    finally:
        conn.close()


def cmd_verify(args: argparse.Namespace) -> int:
    s = Settings.load()
    conn = _connect(s.DB_PATH)
    try:
        cur = conn.execute("SELECT 1 FROM schema_migrations LIMIT 1")
        _ = cur.fetchone()
    except Exception:
        print("schema_migrations missing — running meta-init…")
        # Переинициализация мета-таблицы произойдёт в run_migrations
    try:
        run_migrations(conn, now_ms=args.now_ms or 0)  # проверит checksums и dirty
        print("verification OK")
        return 0
    except Exception as exc:
        print(f"verification FAILED: {exc}")
        return 2
    finally:
        conn.close()


def cmd_backup_before_fix(args: argparse.Namespace) -> int:
    # делаем онлайн-бэкап перед ручными операциями
    from .db_backup import do_backup
    s = Settings.load()
    out = do_backup(db_path=s.DB_PATH, out_dir=s.DB_BACKUP_DIR, compress=s.DB_BACKUP_COMPRESS)
    print(f"backup: {out}")
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="migrate_repair", description="SQLite migration repair utilities")
    sub = p.add_subparsers(required=True)

    s1 = sub.add_parser("show", help="list applied migrations")
    s1.set_defaults(func=cmd_show)

    s2 = sub.add_parser("clear-dirty", help="set dirty=0 for all")
    s2.set_defaults(func=cmd_clear_dirty)

    s3 = sub.add_parser("delete", help="delete a specific version from meta")
    s3.add_argument("version")
    s3.set_defaults(func=cmd_delete)

    s4 = sub.add_parser("vacuum", help="VACUUM the database")
    s4.set_defaults(func=cmd_vacuum)

    s5 = sub.add_parser("verify", help="verify checksums & meta, run no-op migrations")
    s5.add_argument("--now-ms", type=int, default=0)
    s5.set_defaults(func=cmd_verify)

    s6 = sub.add_parser("backup-before-fix", help="online backup before repairs")
    s6.set_defaults(func=cmd_backup_before_fix)

    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())