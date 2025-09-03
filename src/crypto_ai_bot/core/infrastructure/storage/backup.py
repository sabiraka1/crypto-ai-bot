from __future__ import annotations

import os
from pathlib import Path
import shutil

from crypto_ai_bot.utils.logging import get_logger


_log = get_logger("storage.backup")


def backup_database(src_path: str, backup_dir: str) -> str:
    """Ğ¡Ğ¾Ğ·Ğ´Ğ°ĞµÑ‚ Ñ€ĞµĞ·ĞµÑ€Ğ²Ğ½ÑƒÑ ĞºĞ¾Ğ¿Ğ¸Ñ Ğ‘Ğ”."""
    try:
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Source database not found: {src_path}")

        os.makedirs(backup_dir, exist_ok=True)

        # Ğ“ĞµĞ½ĞµÑ€Ğ¸Ñ€ÑƒĞµĞ¼ Ğ¸Ğ¼Ñ Ğ´Ğ»Ñ Ğ±ÑĞºĞ°Ğ¿Ğ°
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{src.stem}_backup_{timestamp}{src.suffix}"
        dst = Path(backup_dir) / backup_name

        # ĞšĞ¾Ğ¿Ğ¸Ñ€ÑƒĞµĞ¼ Ñ„Ğ°Ğ¹Ğ»
        if hasattr(src, "backup"):
            src.backup(dst)  # Ğ´Ğ»Ñ sqlite3 Connection
        else:
            shutil.copy2(src, dst)

        _log.info("backup_created", extra={"src": str(src), "dst": str(dst)})
        return str(dst)

    except Exception as e:
        _log.error("backup_failed", extra={"error": str(e)})
        raise
