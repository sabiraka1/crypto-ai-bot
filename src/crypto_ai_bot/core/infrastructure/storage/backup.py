from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta


def backup_db(db_path: str, out_dir: str | None = None, retention_days: int = 30) -> str | None:
    """
    Делает бэкап SQLite-файла через API backup(). Возвращает путь к бэкапу или None.
    """
    if not os.path.exists(db_path):
        return None
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(out_dir, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    base = os.path.basename(db_path)
    name = os.path.splitext(base)[0]
    out_path = os.path.join(out_dir, f"{name}-backup-{ts}.sqlite3")

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out_path)
    with dst:
        src.backup(dst)  # type: ignore[attr-defined]
    src.close()
    dst.close()

    # ротация
    cutoff = datetime.now(UTC) - timedelta(days=int(retention_days))
    for f in os.listdir(out_dir):
        if not f.endswith(".sqlite3"):
            continue
        full = os.path.join(out_dir, f)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(full), tz=UTC)
            if mtime < cutoff:
                os.remove(full)
        except Exception:
            pass

    return out_path
