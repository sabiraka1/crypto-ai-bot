from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("storage.backup")


def backup_database(src_path: str, backup_dir: str) -> str:
    """Создает резервную копию БД."""
    try:
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Source database not found: {src_path}")
            
        os.makedirs(backup_dir, exist_ok=True)
        
        # Генерируем имя для бэкапа
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{src.stem}_backup_{timestamp}{src.suffix}"
        dst = Path(backup_dir) / backup_name
        
        # Копируем файл
        if hasattr(src, "backup"):
            src.backup(dst)  # для sqlite3 Connection
        else:
            shutil.copy2(src, dst)
            
        _log.info("backup_created", extra={"src": str(src), "dst": str(dst)})
        return str(dst)
        
    except Exception as e:
        _log.error("backup_failed", extra={"error": str(e)})
        raise