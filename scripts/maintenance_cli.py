#!/usr/bin/env python3
# scripts/maintenance_cli.py
from __future__ import annotations
import argparse
import os
from datetime import datetime
from pathlib import Path
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

def cmd_backup(db_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = out / f"bot-{ts}.sqlite"
    # simple file copy
    data = Path(db_path).read_bytes()
    target.write_bytes(data)
    logger.info("DB backup saved: %s (%d bytes)", target, len(data))

def cmd_cleanup_idempotency(ttl_ms: int) -> None:
    c = build_container()
    removed = getattr(c.idempotency_repo, "cleanup_expired", lambda ttl: 0)(ttl_ms)
    logger.info("Idempotency cleanup done: removed=%s ttl_ms=%s", removed, ttl_ms)

def main() -> None:
    ap = argparse.ArgumentParser("maintenance_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backup", help="Backup SQLite DB to directory")
    b.add_argument("--db", default=os.environ.get("DB_PATH", "/data/bot.sqlite"))
    b.add_argument("--out", default="./backups")

    c = sub.add_parser("cleanup-idem", help="Cleanup expired idempotency keys")
    c.add_argument("--ttl-ms", type=int, default=10 * 60_000)

    args = ap.parse_args()
    if args.cmd == "backup":
        cmd_backup(args.db, args.out)
    elif args.cmd == "cleanup-idem":
        cmd_cleanup_idempotency(args.ttl_ms)

if __name__ == "__main__":
    main()
