#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def vacuum(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute("VACUUM")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path, help="path to SQLite DB")
    args = ap.parse_args()
    vacuum(args.db)
    print("OK")


if __name__ == "__main__":
    main()