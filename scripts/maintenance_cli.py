#!/usr/bin/env python3
# scripts/maintenance_cli.py
"""
Простой CLI для Railway Cron:
- Бэкап SQLite в /data/backups/bot-YYYYmmdd-HHMMSS.sqlite
- Мягкая очистка idempotency, если есть колонка expires_at (опционально)
Запуск:
  python scripts/maintenance_cli.py backup
  python scripts/maintenance_cli.py cleanup
"""
from __future__ import annotations

import os
import sys
import shutil
from datetime import datetime

from crypto_ai_bot.app.compose import build_container

def ensure_dir(path: str) -> None:
    if path:
        os.makedirs(path, exist_ok=True)

def backup_db() -> None:
    c = build_container()
    db_path = c.settings.DB_PATH
    dst_dir = "/data/backups"
    ensure_dir(dst_dir)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(dst_dir, f"bot-{ts}.sqlite")
    # SQLite-совместимая копия выключенным соединением (у нас один процесс)
    c.db.commit()
    c.db.execute("PRAGMA wal_checkpoint(FULL)")
    c.db.commit()
    shutil.copy2(db_path, dst)
    print(f"Backup created: {dst}")

def cleanup_idempotency() -> None:
    """
    Мягкий DELETE: если существует таблица idempotency и поле expires_at — удаляем просроченные.
    Ничего не рушим, если схемы нет.
    """
    c = build_container()
    cur = c.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency'")
    if not cur.fetchone():
        print("No idempotency table — skip.")
        return

    info = c.db.execute("PRAGMA table_info('idempotency')").fetchall()
    cols = {row[1] for row in info}
    if "expires_at" not in cols:
        print("No expires_at column — skip cleanup.")
        return

    c.db.execute("DELETE FROM idempotency WHERE expires_at <= strftime('%s','now')*1000")
    c.db.commit()
    print("Idempotency cleanup done.")

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: maintenance_cli.py [backup|cleanup]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "backup":
        backup_db()
    elif cmd == "cleanup":
        cleanup_idempotency()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(2)

if __name__ == "__main__":
    main()
