#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    # Проверка целостности БД/состояний
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "crypto_ai_bot.cli.maintenance", "integrity"],
        check=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
