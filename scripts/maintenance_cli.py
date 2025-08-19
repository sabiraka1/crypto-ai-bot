#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict

# --- make sure we can import from src/ ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from crypto_ai_bot.app.compose import build_container  # type: ignore
from crypto_ai_bot.core.storage.maintenance import maintenance_once  # type: ignore


def _configure_logging(default_level: str = "INFO") -> None:
    level = os.getenv("LOG_LEVEL", default_level).upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def run_once(apply_pragmas: bool) -> Dict[str, Any]:
    c = build_container()  # DI без сайд-эффектов (bus/orchestrator не стартуют)
    try:
        summary = maintenance_once(
            conn=c.con,
            idempotency_repo=c.idempotency_repo,
            apply_pragmas=apply_pragmas,
        )
        return {
            "ok": True,
            "idempotency_removed": summary.get("idempotency_removed", 0),
            "db_metrics": summary.get("db_metrics", {}),
        }
    finally:
        try:
            c.con.close()
        except Exception:
            pass


def main() -> int:
    _configure_logging()

    ap = argparse.ArgumentParser(
        description="Maintenance: SQLite housekeeping + idempotency cleanup"
    )
    ap.add_argument(
        "--apply-pragmas",
        action="store_true",
        help="Apply safe PRAGMAs (WAL, busy_timeout, etc.) before cleanup",
    )
    ap.add_argument(
        "--every",
        type=float,
        default=0.0,
        help="If > 0: run in a loop every N seconds (daemon mode). Default: run once.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON to stdout",
    )
    args = ap.parse_args()

    log = logging.getLogger("maintenance_cli")

    if args.every and args.every > 0:
        log.info("Maintenance daemon started (every %.2f sec, apply_pragmas=%s)", args.every, args.apply_pragmas)
        try:
            while True:
                t0 = time.time()
                res = run_once(apply_pragmas=args.apply_pragmas)
                if args.json:
                    print(json.dumps(res, ensure_ascii=False))
                else:
                    log.info("Cleanup done: removed=%s db=%s", res.get("idempotency_removed"), res.get("db_metrics"))
                elapsed = time.time() - t0
                sleep_for = max(0.0, args.every - elapsed)
                time.sleep(sleep_for)
        except KeyboardInterrupt:
            log.info("Maintenance daemon stopped by user")
            return 0
    else:
        res = run_once(apply_pragmas=args.apply_pragmas)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            log.info("Cleanup done: removed=%s db=%s", res.get("idempotency_removed"), res.get("db_metrics"))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
