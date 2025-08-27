import pytest
import tempfile
from pathlib import Path
from crypto_ai_bot.cli.maintenance import _backup, _rotate, _integrity

def test_backup_creates_file():
    with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
        db_path = f.name
    
    try:
        backup_path = _backup(db_path)
        assert backup_path is not None
        assert Path(backup_path).exists()
        Path(backup_path).unlink(missing_ok=True)
    finally:
        Path(db_path).unlink(missing_ok=True)

def test_integrity_check():
    import sqlite3
    with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as f:
        db_path = f.name
    
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE test(id INTEGER)")
    conn.close()
    
    try:
        _integrity(db_path)  # Не должно выбросить исключение
    finally:
        Path(db_path).unlink(missing_ok=True)