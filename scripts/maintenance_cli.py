#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
try:
    from crypto_ai_bot.core.settings import Settings  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"[maintenance] failed to import Settings: {e}", file=sys.stderr)
    Settings = None  # type: ignore
try:
    from crypto_ai_bot.utils.logging import get_logger  # type: ignore
except Exception:  # pragma: no cover
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    def get_logger(name):  # type: ignore
        return logging.getLogger(name)
logger = get_logger(__name__)
def _ensure_dir(p: str) -> None:
    if not p:
        return
    Path(p).mkdir(parents=True, exist_ok=True)
def _connect(db_path: str) -> sqlite3.Connection:
    _ensure_dir(os.path.dirname(db_path))
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA mmap_size=30000000000;")  # best-effort
    return conn
def cmd_backup(args, settings) -> int:
    db_path = settings.DB_PATH
    backup_dir = os.getenv("DB_BACKUP_DIR", "/data/backups")
    _ensure_dir(backup_dir)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(backup_dir, f"bot-{ts}.sqlite")
    logger.info("Backing up DB: %s -> %s", db_path, dst)
    src = _connect(db_path)
    try:
        dst_conn = sqlite3.connect(dst)
        with dst_conn:
            src.backup(dst_conn)  # sqlite native backup
        logger.info("Backup created: %s", dst)
    finally:
        src.close()
    keep = int(os.getenv("DB_BACKUP_KEEP", "14"))  # дней
    try:
        purge_before = time.time() - keep * 86400
        for p in Path(backup_dir).glob("bot-*.sqlite"):
            if p.stat().st_mtime < purge_before:
                logger.info("Removing old backup: %s", p)
                with suppress_err():
                    p.unlink()
    except Exception as e:
        logger.warning("backup retention failed: %s", e)
    return 0
def cmd_cleanup_idempotency(args, settings) -> int:
    db_path = settings.DB_PATH
    now_ms = int(time.time() * 1000)
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM idempotency WHERE expires_at_ms IS NOT NULL AND expires_at_ms <= ?", (now_ms,))
        except sqlite3.OperationalError:
            try:
                cur.execute(
                    "DELETE FROM idempotency WHERE created_at_ms IS NOT NULL AND ttl_sec IS NOT NULL AND (created_at_ms + ttl_sec*1000) <= ?",
                    (now_ms,),
                )
            except sqlite3.OperationalError:
                logger.warning("idempotency table schema not recognized; skipping cleanup")
                return 0
        logger.info("idempotency cleanup done, rows=%s", cur.rowcount if hasattr(cur, "rowcount") else "?")
        return 0
    finally:
        conn.close()
def cmd_vacuum(args, settings) -> int:
    conn = _connect(settings.DB_PATH)
    try:
        conn.execute("VACUUM;")
        logger.info("VACUUM completed")
        return 0
    finally:
        conn.close()
class suppress_err:
    def __enter__(self):  # pragma: no cover
        return self
    def __exit__(self, exc_type, exc, tb):  # pragma: no cover
        return True
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Maintenance CLI for crypto-ai-bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup-db", help="Create sqlite backup to DB_BACKUP_DIR")
    sub.add_parser("cleanup-idempotency", help="Delete expired idempotency keys")
    sub.add_parser("vacuum", help="Run VACUUM on sqlite DB")
    sub.add_parser("backup-and-clean", help="Backup DB and cleanup idempotency keys")
    return p
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if Settings is None:
        print("[maintenance] Settings unavailable", file=sys.stderr)
        return 2
    settings = Settings.load()
    if args.cmd == "backup-db":
        return cmd_backup(args, settings)
    if args.cmd == "cleanup-idempotency":
        return cmd_cleanup_idempotency(args, settings)
    if args.cmd == "vacuum":
        return cmd_vacuum(args, settings)
    if args.cmd == "backup-and-clean":
        rc = cmd_backup(args, settings)
        rc2 = cmd_cleanup_idempotency(args, settings)
        return rc or rc2
    parser.print_help()
    return 2
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
