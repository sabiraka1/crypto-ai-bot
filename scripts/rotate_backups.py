#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rotate local backups by age.")
    parser.add_argument("--days", type=int, default=30, help="Keep backups newer than N days (default: 30)")
    args = parser.parse_args(argv)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "crypto_ai_bot.cli.maintenance",
            "rotate",
            "--days",
            str(args.days),
        ],
        check=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
