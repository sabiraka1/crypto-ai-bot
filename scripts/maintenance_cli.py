#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

# используем готовые онлайн-бэкапы, чтобы не дублировать логику
from crypto_ai_bot.app.db_backup import (
    do_backup as backup_run,
    do_prune as backup_prune,
    do_restore as backup_restore,
)

log = get_logger("maintenance")


class MaintenanceDB:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

    def cleanup_idempotency(self, days: int = 7) -> int:
        cutoff_ms = now_ms() - days * 86400 * 1000
        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                cur = conn.execute(
                    "DELETE FROM idempotency_keys WHERE expires_at_ms < ?",
                    (cutoff_ms,),
                )
                deleted = cur.rowcount or 0
            except sqlite3.OperationalError:
                deleted = 0  # нет таблицы — ничего страшного
        log.info("idempotency_cleaned", extra={"deleted": deleted, "older_than_days": days})
        return deleted

    def cleanup_audit(self, days: int = 30) -> int:
        cutoff_ms = now_ms() - days * 86400 * 1000
        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                cur = conn.execute(
                    "DELETE FROM audit_log WHERE ts_ms < ?",
                    (cutoff_ms,),
                )
                deleted = cur.rowcount or 0
            except sqlite3.OperationalError:
                deleted = 0
        log.info("audit_cleaned", extra={"deleted": deleted, "older_than_days": days})
        return deleted

    def vacuum(self) -> Dict[str, Any]:
        with sqlite3.connect(str(self.db_path)) as conn:
            # до
            try:
                cur = conn.execute(
                    "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
                )
                size_before = int(cur.fetchone()[0])
            except Exception:
                size_before = 0
            # статистика фри-листов
            try:
                cur = conn.execute("PRAGMA freelist_count")
                freelist = int(cur.fetchone()[0])
            except Exception:
                freelist = 0

            conn.execute("VACUUM")
            conn.execute("ANALYZE")

            # после
            try:
                cur = conn.execute(
                    "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
                )
                size_after = int(cur.fetchone()[0])
            except Exception:
                size_after = 0

        saved = max(size_before - size_after, 0)
        stats = {
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "saved_bytes": saved,
            "saved_pct": (saved / size_before * 100.0) if size_before > 0 else 0.0,
            "fragmentation_pages": freelist,
        }
        log.info("vacuum_completed", extra=stats)
        return stats

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            # размер
            try:
                cur = conn.execute(
                    "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
                )
                stats["size_bytes"] = int(cur.fetchone()[0])
                stats["size_mb"] = stats["size_bytes"] / 1024.0 / 1024.0
            except Exception:
                stats["size_bytes"] = 0
                stats["size_mb"] = 0.0

            # количество записей по таблицам (если есть)
            for tbl in ("trades", "positions", "audit_log", "idempotency_keys"):
                try:
                    cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
                    stats[f"{tbl}_count"] = int(cur.fetchone()[0])
                except sqlite3.OperationalError:
                    stats[f"{tbl}_count"] = 0

            # временной охват сделок
            try:
                cur = conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM trades")
                mn, mx = cur.fetchone()
                if mn and mx:
                    stats["oldest_trade_ms"] = int(mn)
                    stats["newest_trade_ms"] = int(mx)
                    stats["trade_days"] = (mx - mn) / (86400 * 1000)
            except sqlite3.OperationalError:
                pass

            # фрагментация
            try:
                cur = conn.execute("PRAGMA freelist_count")
                stats["fragmentation_pages"] = int(cur.fetchone()[0])
            except Exception:
                stats["fragmentation_pages"] = 0

        return stats

    def integrity_check(self) -> bool:
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("PRAGMA integrity_check")
            res = str(cur.fetchone()[0])
        ok = (res == "ok")
        log.info("integrity_check", extra={"ok": ok, "result": res})
        return ok


def _resolve_db_and_dirs(args: argparse.Namespace) -> tuple[str, str]:
    # Если путь не указан, берём из Settings
    s = Settings.load()
    db = args.db or s.DB_PATH
    backup_dir = args.dir or s.DB_BACKUP_DIR
    return db, backup_dir


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Database maintenance tools")
    p.add_argument("--db", default=None, help="Path to sqlite db (default: Settings.DB_PATH)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # backup
    b = sub.add_parser("backup-db", help="Create compressed online backup")
    b.add_argument("--dir", default=None, help="Backup directory (default: Settings.DB_BACKUP_DIR)")
    b.add_argument("--compress", action="store_true", default=False)
    b.add_argument("--retention-days", type=int, default=0)

    # prune backups
    pr = sub.add_parser("prune-backups", help="Prune old backups")
    pr.add_argument("--dir", default=None)
    pr.add_argument("--retention-days", type=int, default=7)

    # restore
    r = sub.add_parser("restore-db", help="Restore db from backup file")
    r.add_argument("--file", required=True, help="Path to backup file (.sqlite3 or .gz)")

    # cleanup data
    c = sub.add_parser("cleanup", help="Cleanup old rows")
    c.add_argument("--days", type=int, default=7)
    c.add_argument(
        "--what",
        choices=["all", "idempotency", "audit"],
        default="all",
        help="What to clean",
    )

    # vacuum/analyze
    sub.add_parser("vacuum", help="Optimize database")

    # stats, integrity
    sub.add_parser("stats", help="Show db statistics")
    sub.add_parser("integrity", help="Run PRAGMA integrity_check")

    args = p.parse_args(argv)
    db_path, backup_dir = _resolve_db_and_dirs(args)

    try:
        if args.cmd == "backup-db":
            out = backup_run(db_path=db_path, out_dir=backup_dir, compress=bool(args.compress))
            if args.retention_days > 0:
                removed = backup_prune(out_dir=backup_dir, retention_days=args.retention_days)
                print(f"removed_old_backups={removed}")
            print(out)
            return 0

        if args.cmd == "prune-backups":
            removed = backup_prune(out_dir=backup_dir, retention_days=int(args.retention_days))
            print(f"removed={removed}")
            return 0

        m = MaintenanceDB(db_path)

        if args.cmd == "cleanup":
            total_deleted = 0
            if args.what in ("all", "idempotency"):
                total_deleted += m.cleanup_idempotency(days=int(args.days))
            if args.what in ("all", "audit"):
                total_deleted += m.cleanup_audit(days=int(args.days))
            print(f"deleted_rows={total_deleted}")
            return 0

        if args.cmd == "vacuum":
            stats = m.vacuum()
            print(json.dumps(stats, indent=2))
            return 0

        if args.cmd == "stats":
            stats = m.get_stats()
            print(json.dumps(stats, indent=2))
            return 0

        if args.cmd == "integrity":
            ok = m.integrity_check()
            print("ok" if ok else "fail")
            return 0 if ok else 2

        if args.cmd == "restore-db":
            backup_restore(db_path=db_path, backup_file=args.file)
            print("restored")
            return 0

        raise SystemExit("unknown command")

    except Exception as exc:
        log.error("maintenance_error", extra={"error": str(exc)})
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
