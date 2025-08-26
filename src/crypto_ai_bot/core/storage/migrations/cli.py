from __future__ import annotations

import argparse
import os
import sqlite3
from typing import Optional

from ..backup import backup_db
from .runner import run_migrations
from ...utils.time import now_ms


def _open_conn(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_migrate(db_path: str, do_backup: bool, retention_days: int) -> None:
    conn = _open_conn(db_path)
    version = run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=do_backup, backup_retention_days=retention_days)
    print(f"migrated_to={version}")


def cmd_backup(db_path: str, out_dir: Optional[str], retention_days: int) -> None:
    path = backup_db(db_path, out_dir=out_dir, retention_days=retention_days)
    print(f"backup_created={path}")


def main() -> None:
    p = argparse.ArgumentParser(prog="crypto-ai-bot.migrations", description="DB migrations & backup")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_m = sub.add_parser("migrate", help="Run DB migrations")
    p_m.add_argument("--db", dest="db_path", default=os.getenv("DB_PATH", "./data/trader.sqlite3"))
    p_m.add_argument("--no-backup", action="store_true")
    p_m.add_argument("--retention-days", type=int, default=int(os.getenv("BACKUP_RETENTION_DAYS", "30")))

    p_b = sub.add_parser("backup", help="Make DB backup")
    p_b.add_argument("--db", dest="db_path", default=os.getenv("DB_PATH", "./data/trader.sqlite3"))
    p_b.add_argument("--out", dest="out_dir", default=None)
    p_b.add_argument("--retention-days", type=int, default=int(os.getenv("BACKUP_RETENTION_DAYS", "30")))

    args = p.parse_args()
    if args.cmd == "migrate":
        cmd_migrate(args.db_path, do_backup=(not args.no_backup), retention_days=args.retention_days)
    elif args.cmd == "backup":
        cmd_backup(args.db_path, out_dir=args.out_dir, retention_days=args.retention_days)


if __name__ == "__main__":
    main()
