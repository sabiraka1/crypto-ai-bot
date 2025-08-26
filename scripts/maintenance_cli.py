#!/usr/bin/env python3
"""
Maintenance CLI — резервные копии, очистка и обслуживание БД.

Примеры:
  python -m scripts.maintenance_cli backup-db --dir ./data/backups --compress
  python -m scripts.maintenance_cli prune-backups --dir ./data/backups --retention-days 14
  python -m scripts.maintenance_cli cleanup --what all --days 7
  python -m scripts.maintenance_cli vacuum
  python -m scripts.maintenance_cli stats
  python -m scripts.maintenance_cli integrity
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

log = get_logger("maintenance")


def _resolve_db_path(cli_db: Optional[str]) -> Path:
    if cli_db:
        return Path(cli_db)
    # дефолт — из Settings (учитывает изоляцию по средам)
    s = Settings.load()
    return Path(s.DB_PATH)


class MaintenanceDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

    # ---------- BACKUP ----------
    def backup(self, backup_dir: Path, compress: bool = True) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if compress:
            out = backup_dir / f"backup_{ts}.sql.gz"
        else:
            out = backup_dir / f"backup_{ts}.sql"

        # делаем дамп и (опц.) сжимаем
        with sqlite3.connect(str(self.db_path)) as conn:
            it = conn.iterdump()
            if compress:
                with gzip.open(out, "wb") as f:
                    for line in it:
                        f.write((line + "\n").encode("utf-8"))
            else:
                with open(out, "w", encoding="utf-8") as f:
                    for line in it:
                        f.write(line + "\n")

        size_mb = out.stat().st_size / 1024 / 1024
        log.info("backup_created", extra={"file": str(out), "size_mb": f"{size_mb:.2f}"})
        return out

    def prune_backups(self, backup_dir: Path, retention_days: int) -> int:
        if not backup_dir.exists():
            return 0
        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = 0
        for p in backup_dir.iterdir():
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime < cutoff:
                    p.unlink()
                    deleted += 1
            except Exception:
                pass
        log.info("backups_pruned", extra={"dir": str(backup_dir), "retention_days": retention_days, "deleted": deleted})
        return deleted

    # ---------- CLEANUP ----------
    def cleanup_idempotency(self, days: int) -> int:
        cutoff_ms = now_ms() - days * 86400 * 1000
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("DELETE FROM idempotency_keys WHERE expires_at_ms < ?", (cutoff_ms,))
            return cur.rowcount or 0

    def cleanup_audit(self, days: int) -> int:
        cutoff_ms = now_ms() - days * 86400 * 1000
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("DELETE FROM audit_log WHERE ts_ms < ?", (cutoff_ms,))
            return cur.rowcount or 0

    def cleanup_old_trades(self, days: int, archive_dir: Path = Path("./data/archives")) -> int:
        cutoff_ms = now_ms() - days * 86400 * 1000
        archive_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades WHERE ts_ms < ?", (cutoff_ms,)).fetchall()
            if rows:
                out = archive_dir / f"trades_{datetime.now():%Y%m%d}.jsonl.gz"
                with gzip.open(out, "at") as f:
                    for r in rows:
                        f.write(json.dumps(dict(r)) + "\n")
                conn.execute("DELETE FROM trades WHERE ts_ms < ?", (cutoff_ms,))
                log.info("trades_archived_deleted", extra={"archived": len(rows), "file": str(out)})
                return len(rows)
            return 0

    # ---------- VACUUM & STATS ----------
    def vacuum(self) -> Dict[str, Any]:
        with sqlite3.connect(str(self.db_path)) as conn:
            size_before = conn.execute(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
            ).fetchone()[0]
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
            conn.execute("VACUUM")
            conn.execute("ANALYZE")
            size_after = conn.execute(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
            ).fetchone()[0]
        saved = size_before - size_after
        pct = (saved / size_before * 100) if size_before else 0
        stats = {
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "saved_bytes": saved,
            "saved_pct": pct,
            "fragmentation_pages": freelist,
        }
        log.info("vacuum_completed", extra=stats)
        return stats

    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            size = conn.execute(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
            ).fetchone()[0]
            out = {"size_bytes": size, "size_mb": size / 1024 / 1024}
            for tbl in ("trades", "positions", "audit_log", "idempotency_keys"):
                try:
                    out[f"{tbl}_count"] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                except Exception:
                    out[f"{tbl}_count"] = 0
            try:
                mn, mx = conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM trades").fetchone()
                if mn and mx:
                    out["trade_days"] = (mx - mn) / (86400 * 1000)
            except Exception:
                pass
            out["fragmentation_pages"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
            return out

    # ---------- INTEGRITY ----------
    def integrity(self) -> bool:
        with sqlite3.connect(str(self.db_path)) as conn:
            res = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ok = (res == "ok")
        log.info("integrity_check", extra={"ok": ok, "result": res})
        return ok


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DB maintenance")
    p.add_argument("--db", help="Path to database (defaults to Settings.DB_PATH)")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backup-db", help="Create DB backup")
    b.add_argument("--dir", default="./data/backups", help="Backup directory")
    b.add_argument("--compress", action="store_true", help="Compress .gz")

    s = sub.add_parser("prune-backups", help="Delete old backups")
    s.add_argument("--dir", default="./data/backups", help="Backup directory")
    s.add_argument("--retention-days", type=int, default=14)

    c = sub.add_parser("cleanup", help="Cleanup old data")
    c.add_argument("--days", type=int, default=7)
    c.add_argument("--what", choices=["all", "idempotency", "audit", "trades"], default="all")

    sub.add_parser("vacuum", help="VACUUM & ANALYZE")
    sub.add_parser("stats", help="DB stats")
    sub.add_parser("integrity", help="PRAGMA integrity_check")

    return p


def main() -> int:
    args = _build_parser().parse_args()
    db_path = _resolve_db_path(args.db)
    m = MaintenanceDB(db_path)

    try:
        if args.cmd == "backup-db":
            out = m.backup(Path(args.dir), compress=bool(args.compress))
            print(f"✅ backup: {out}")
        elif args.cmd == "prune-backups":
            n = m.prune_backups(Path(args.dir), args.retention_days)
            print(f"🧹 pruned: {n}")
        elif args.cmd == "cleanup":
            total = 0
            if args.what in ("all", "idempotency"):
                total += m.cleanup_idempotency(args.days)
            if args.what in ("all", "audit"):
                total += m.cleanup_audit(args.days)
            if args.what in ("all", "trades"):
                total += m.cleanup_old_trades(max(args.days * 3, 30))
            print(f"🧽 cleaned: {total}")
        elif args.cmd == "vacuum":
            st = m.vacuum()
            print(json.dumps(st, indent=2))
        elif args.cmd == "stats":
            st = m.stats()
            print(json.dumps(st, indent=2))
        elif args.cmd == "integrity":
            ok = m.integrity()
            print("✅ integrity OK" if ok else "❌ integrity FAILED")
            return 0 if ok else 1
        return 0
    except Exception as e:
        log.error("maintenance_error", extra={"error": str(e)})
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
