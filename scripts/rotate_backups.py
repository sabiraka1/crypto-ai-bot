#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    days = argv[0] if argv else "30"
    return subprocess.run(
        [sys.executable, "-m", "crypto_ai_bot.cli.maintenance", "rotate", "--days", str(days)],
        check=False
    ).returncode

if __name__ == "__main__":
    raise SystemExit(main())
