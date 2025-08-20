#!/usr/bin/env python3
# scripts/maintenance_cli.py
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sqlite3
from datetime import datetime, timezone

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.storage.sqlite_adapter import connect

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def backup_db(db_path: str, dst_dir: str) -> str:
    dst = pathlib.Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    out = dst / f"bot.sqlite.{stamp}.bak"
    # надёжный копийный бэкап (без открытого транзакционного снапшота)
    with connect(db_path) as con:
        # SQLite online backup API
        bck = sqlite3.connect(str(out))
        with bck:
            con.backup(bck)  # type: ignore[attr-defined]
        bck.close()
    return str(out)

def vacuum_db(db_path: str) -> None:
    with connect(db_path) as con:
        con.execute("VACUUM")
        con.commit()

def main() -> int:
    cfg = Settings.load()
    db_path = getattr(cfg, "DB_PATH", ":memory:")
    backup_dir = os.environ.get("BACKUP_DIR", "/data/backups")

    parser = argparse.ArgumentParser(description="DB maintenance CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backup", help="Create SQLite backup into BACKUP_DIR")
    sub.add_parser("vacuum", help="Run VACUUM on SQLite DB")

    args = parser.parse_args()

    if args.cmd == "backup":
        out = backup_db(db_path, backup_dir)
        print(f"Backup created: {out}")
        return 0

    if args.cmd == "vacuum":
        vacuum_db(db_path)
        print("VACUUM done")
        return 0

    return 1

if __name__ == "__main__":
    raise SystemExit(main())
