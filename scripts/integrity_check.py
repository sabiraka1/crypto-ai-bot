#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    return subprocess.run([sys.executable, "-m", "crypto_ai_bot.cli.maintenance", "integrity"], check=False).returncode

if __name__ == "__main__":
    raise SystemExit(main())
