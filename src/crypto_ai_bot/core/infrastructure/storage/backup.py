from __future__ import annotations

import os
from pathlib import Path
import shutil

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("storage.backup")


def backup_database(src_path: str, backup_dir: str) -> str:
    """Create a backup copy of the database."""
    try:
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Source database not found: {src_path}")

        os.makedirs(backup_dir, exist_ok=True)

        # Generate name for backup
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{src.stem}_backup_{timestamp}{src.suffix}"
        dst = Path(backup_dir) / backup_name

        # Copy the file
        if hasattr(src, "backup"):
            src.backup(dst)  # For sqlite3 Connection
        else:
            shutil.copy2(src, dst)

        _log.info("backup_created", extra={"src": str(src), "dst": str(dst)})
        return str(dst)

    except Exception as e:
        _log.error("backup_failed", extra={"error": str(e)})
        raise
