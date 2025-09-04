#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    # Безопасный запуск: без shell, с check=True
    result = subprocess.run(
        [sys.executable, "-m", "crypto_ai_bot.cli.maintenance", "backup"],
        check=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
