#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# репозиторные импорты
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from crypto_ai_bot.core.settings import Settings  # noqa: E402


BACKUPS_DIR = Path("./backups")


def _db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_backup(db_path: str) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst = BACKUPS_DIR / f"db-{stamp}.sqlite3"
    # безопасное копирование с блокировкой чтения
    src = Path(db_path)
    if not src.exists():
        raise SystemExit(f"DB not found: {src}")
    shutil.copy2(src, dst)
    print(f"[OK] backup -> {dst}")
    return dst


def cmd_rotate(retention_days: int) -> None:
    if not BACKUPS_DIR.exists():
        print("[OK] no backups to rotate")
        return
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    removed = 0
    for p in BACKUPS_DIR.glob("db-*.sqlite3"):
        ts = p.name.split("-")[1].split(".")[0]  # YYYYmmdd-HHMMSS
        try:
            dt = datetime.strptime(ts, "%Y%m%d")
        except ValueError:
            # полная точность по времени, если есть дефис
            try:
                dt = datetime.strptime(ts, "%Y%m%d")
            except Exception:
                continue
        # если в имени есть и время
        try:
            dt = datetime.strptime(p.name[3:3+15], "%Y%m%d-%H%M%S")
        except Exception:
            pass
        if dt < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    print(f"[OK] rotate -> removed={removed}, retention_days={retention_days}")


def cmd_vacuum(db_path: str) -> None:
    conn = _db_connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("VACUUM;")
        conn.commit()
        print("[OK] vacuum")
    finally:
        conn.close()


def cmd_integrity(db_path: str) -> None:
    conn = _db_connect(db_path)
    try:
        cur = conn.execute("PRAGMA integrity_check;")
        res = cur.fetchone()[0]
        ok = (res == "ok")
        print(f"[{ 'OK' if ok else 'FAIL' }] integrity_check -> {res}")
        if not ok:
            raise SystemExit(2)
    finally:
        conn.close()


def cmd_list() -> None:
    if not BACKUPS_DIR.exists():
        print("(empty)")
        return
    for p in sorted(BACKUPS_DIR.glob("db-*.sqlite3")):
        print(p.name)


def main(argv: Optional[list[str]] = None) -> int:
    settings = Settings.load()
    parser = argparse.ArgumentParser(prog="maintenance_cli", description="DB maintenance: backup/rotate/vacuum/integrity")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backup", help="create backup of DB")
    p_rot = sub.add_parser("rotate", help="remove old backups by retention days")
    p_rot.add_argument("--days", type=int, default=settings.BACKUP_RETENTION_DAYS)

    sub.add_parser("vacuum", help="VACUUM the DB")
    sub.add_parser("integrity", help="PRAGMA integrity_check")
    sub.add_parser("list", help="list available backups")

    args = parser.parse_args(argv)

    if args.cmd == "backup":
        cmd_backup(settings.DB_PATH)
        return 0
    if args.cmd == "rotate":
        cmd_rotate(args.days)
        return 0
    if args.cmd == "vacuum":
        cmd_vacuum(settings.DB_PATH)
        return 0
    if args.cmd == "integrity":
        cmd_integrity(settings.DB_PATH)
        return 0
    if args.cmd == "list":
        cmd_list()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
