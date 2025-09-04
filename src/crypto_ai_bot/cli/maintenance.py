from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sqlite3

from crypto_ai_bot.core.infrastructure.settings import Settings

BACKUPS_DIR = Path("./backups")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _backup(db_path: str) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst = BACKUPS_DIR / f"db-{stamp}.sqlite3"
    src = Path(db_path)
    if not src.exists():
        raise SystemExit(f"DB not found: {src}")
    shutil.copy2(src, dst)
    print(f"[OK] backup -> {dst}")
    return dst


def _rotate(retention_days: int) -> None:
    if not BACKUPS_DIR.exists():
        print("[OK] no backups to rotate")
        return
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    removed = 0
    for p in BACKUPS_DIR.glob("db-*.sqlite3"):
        try:
            stem = p.stem  # "db-20240101-123456"
            parts = stem.split("-")
            if len(parts) >= 2:
                date_part = parts[1]
                time_part = parts[2] if len(parts) > 2 else ""
                if time_part:
                    dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
                else:
                    dt = datetime.strptime(date_part, "%Y%m%d")

                if dt < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
        except Exception:
            continue
    print(f"[OK] rotate -> removed={removed}, retention_days={retention_days}")


def _vacuum(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("VACUUM;")
        conn.commit()
        print("[OK] vacuum")
    finally:
        conn.close()


def _integrity(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.execute("PRAGMA integrity_check;")
        res = cur.fetchone()[0]
        ok = res == "ok"
        print(f"[{'OK' if ok else 'FAIL'}] integrity_check -> {res}")
        if not ok:
            raise SystemExit(2)
    finally:
        conn.close()


def _list() -> None:
    if not BACKUPS_DIR.exists():
        print("(empty)")
        return
    for p in sorted(BACKUPS_DIR.glob("db-*.sqlite3")):
        print(p.name)


def main(argv: list[str] | None = None) -> int:
    settings = Settings.load()
    parser = argparse.ArgumentParser(prog="cab-maintenance", description="DB maintenance")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backup")

    p_rot = sub.add_parser("rotate")
    p_rot.add_argument("--days", type=int, default=settings.BACKUP_RETENTION_DAYS)

    sub.add_parser("vacuum")
    sub.add_parser("integrity")
    sub.add_parser("list")

    args = parser.parse_args(argv)

    command = args.cmd  # Переименовали cmd в command

    if command == "backup":
        _backup(settings.DB_PATH)
        return 0
    if command == "rotate":
        _rotate(args.days)
        return 0
    if command == "vacuum":
        _vacuum(settings.DB_PATH)
        return 0
    if command == "integrity":
        _integrity(settings.DB_PATH)
        return 0
    if command == "list":
        _list()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
