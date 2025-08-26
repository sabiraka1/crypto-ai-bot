from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from ..core.settings import Settings
except Exception:
    Settings = None  # допускаем вызов с путями напрямую


def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _integrity_check(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA integrity_check;")
        ok = cur.fetchone()[0]
        return ok == "ok"
    finally:
        conn.close()


def do_backup(*, db_path: str, out_dir: str, compress: bool = False) -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = _ts()
    out = str(Path(out_dir) / f"db-{ts}.sqlite3")

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()

    if not _integrity_check(out):
        raise RuntimeError("backup integrity_check failed")

    if compress:
        gz = out + ".gz"
        with open(out, "rb") as f_in, gzip.open(gz, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(out)
        out = gz
    return out


def do_prune(*, out_dir: str, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    base = Path(out_dir)
    if not base.exists():
        return 0
    now = datetime.utcnow()
    removed = 0
    for p in base.iterdir():
        if not p.is_file():
            continue
        age = now - datetime.utcfromtimestamp(p.stat().st_mtime)
        if age > timedelta(days=retention_days):
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
    return removed


def do_restore(*, db_path: str, backup_file: str) -> None:
    # ответственность остановить процессы — на операторе/CI
    tmp = db_path + ".restore_tmp"
    shutil.copy2(backup_file, tmp)
    if not _integrity_check(tmp):
        os.remove(tmp)
        raise RuntimeError("restore integrity_check failed")
    shutil.copy2(tmp, db_path)
    os.remove(tmp)


# --- CLI ---

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="db_backup", description="SQLite online backup tool")
    ap.add_argument("command", choices=["run", "verify", "prune", "restore"])
    ap.add_argument("--db", dest="db", default=None)
    ap.add_argument("--out", dest="out", default=None)
    ap.add_argument("--compress", action="store_true")
    ap.add_argument("--retention-days", type=int, default=0)
    ap.add_argument("--file", dest="file", default=None)
    args = ap.parse_args(argv)

    if Settings and not args.db:
        s = Settings.load()
        args.db = s.DB_PATH
        args.out = args.out or s.DB_BACKUP_DIR

    if args.command == "run":
        dest = do_backup(db_path=args.db, out_dir=args.out, compress=args.compress)
        print(dest)
    elif args.command == "verify":
        print("ok" if _integrity_check(args.db) else "fail")
    elif args.command == "prune":
        removed = do_prune(out_dir=args.out, retention_days=args.retention_days)
        print(f"removed={removed}")
    elif args.command == "restore":
        if not args.file:
            raise SystemExit("--file is required for restore")
        do_restore(db_path=args.db, backup_file=args.file)
        print("restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())