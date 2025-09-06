"""Database backup utility.

Located in infrastructure/storage layer - handles database backups.
Supports online SQLite backup, compression, rotation, integrity metadata, and restore.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import tempfile
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any, Dict, List

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


class DatabaseBackup:
    """Database backup manager with compression and rotation."""

    def __init__(
        self,
        backup_dir: str = "./backups",
        compress: bool = True,
        keep_days: int = 7,
        *,
        keep_last: Optional[int] = None,
        sqlite_online: bool = True,
    ):
        """
        Args:
            backup_dir: каталог для хранения бэкапов
            compress: gzip-сжатие итогового файла
            keep_days: хранить файлы не дольше N дней (<=0 отключает)
            keep_last: опционально — хранить не более N последних бэкапов (доудаляя самые старые)
            sqlite_online: использовать безопасный онлайн-бэкап SQLite (рекомендовано)
        """
        self.backup_dir = Path(backup_dir)
        self.compress = bool(compress)
        self.keep_days = int(keep_days)
        self.keep_last = keep_last if (keep_last is None or keep_last >= 0) else None
        self.sqlite_online = bool(sqlite_online)

    # ------------- public API -------------

    def backup(
        self,
        src_path: str,
        description: Optional[str] = None
    ) -> str:
        """
        Create database backup.

        Args:
            src_path: путь к файлу SQLite (или совместимой БД-файлу)
            description: произвольное описание (попадёт в метаданные)

        Returns:
            Абсолютный путь к созданному бэкапу
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Database not found: {src_path}")

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate backup filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = f"{src.stem}_{timestamp}"

        if description:
            # Sanitize description for filename
            safe_desc = "".join(c if c.isalnum() or c in "-_" else "_" for c in description)
            base_name += f"_{safe_desc}"

        # Create plain (uncompressed) backup first for integrity/hashing
        plain_backup = self.backup_dir / f"{base_name}.sqlite3"
        self._create_sqlite_backup(src, plain_backup)

        # Optionally compress
        final_backup: Path
        if self.compress:
            final_backup = self.backup_dir / f"{base_name}.sqlite3.gz"
            self._gzip_atomic(plain_backup, final_backup)
            # remove the intermediate plain file after successful compression
            try:
                plain_backup.unlink(missing_ok=True)
            except Exception:
                _log.warning("backup_intermediate_unlink_failed", extra={"path": str(plain_backup)})
        else:
            final_backup = plain_backup

        # Save metadata (with checksum)
        checksum = self._sha256(final_backup)
        self._save_metadata(final_backup, src, description, checksum=checksum)

        # Rotate old backups
        self._rotate()

        _log.info(
            "backup_created",
            extra={
                "src": str(src.resolve()),
                "dst": str(final_backup.resolve()),
                "compressed": self.compress,
                "size_mb": round(final_backup.stat().st_size / (1024 * 1024), 3),
                "sha256": checksum,
            },
        )

        return str(final_backup)

    def list_backups(self) -> List[Dict[str, Any]]:
        """List available backups with metadata (best effort)."""
        items: List[Dict[str, Any]] = []

        for backup_file in sorted(self._iter_backup_files()):
            info: Dict[str, Any] = {
                "path": str(backup_file.resolve()),
                "name": backup_file.name,
                "size_mb": round(backup_file.stat().st_size / (1024 * 1024), 3),
                "modified": datetime.fromtimestamp(
                    backup_file.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }

            meta = self._read_metadata_for(backup_file)
            if meta:
                info.update(meta)

            items.append(info)

        return items

    def restore(self, backup_path: str, dst_path: str, *, verify_hash: bool = True, overwrite: bool = False) -> str:
        """
        Restore a backup to destination path.

        Args:
            backup_path: путь к файлу бэкапа (.sqlite3 или .sqlite3.gz)
            dst_path: куда восстановить файл БД
            verify_hash: проверять sha256 из метаданных (если доступны)
            overwrite: разрешить перезапись существующего dst_path

        Returns:
            Абсолютный путь к восстановленному файлу БД
        """
        src = Path(backup_path)
        if not src.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        dst = Path(dst_path)
        if dst.exists() and not overwrite:
            raise FileExistsError(f"Destination exists: {dst_path} (use overwrite=True)")

        # Verify checksum if possible
        meta = self._read_metadata_for(src)
        if verify_hash and meta and "sha256" in meta:
            actual = self._sha256(src)
            if actual != meta["sha256"]:
                raise ValueError(f"Checksum mismatch for {src.name}: expected {meta['sha256']}, got {actual}")

        # Decompress if needed
        if src.suffix == ".gz":
            with gzip.open(src, "rb") as fin, tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
                shutil.copyfileobj(fin, tmp)
                tmp_path = Path(tmp.name)
            self._atomic_replace(tmp_path, dst)
        else:
            # direct copy via temp for atomic replace
            with open(src, "rb") as fin, tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
                shutil.copyfileobj(fin, tmp)
                tmp_path = Path(tmp.name)
            self._atomic_replace(tmp_path, dst)

        # permissions 0600
        self._chmod_600(dst)

        _log.info("backup_restored", extra={"src": str(src), "dst": str(dst)})
        return str(dst.resolve())

    # ------------- internals -------------

    def _create_sqlite_backup(self, src: Path, dst: Path) -> None:
        """Create a consistent SQLite backup using the online backup API (or safe copy fallback)."""
        # Always write to a temp file first
        tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=dst.stem + "_", suffix=dst.suffix, dir=str(self.backup_dir))
        os.close(tmp_fd)
        tmp_path = Path(tmp_path_str)

        try:
            if self.sqlite_online:
                # Use online backup API for consistency even under writes
                src_conn = sqlite3.connect(str(src), timeout=30, isolation_level=None)
                try:
                    dst_conn = sqlite3.connect(str(tmp_path), timeout=30, isolation_level=None)
                    try:
                        src_conn.backup(dst_conn)  # Copy entire DB
                    finally:
                        dst_conn.close()
                finally:
                    src_conn.close()
            else:
                # Fallback: copy file contents
                with open(src, "rb") as fin, open(tmp_path, "wb") as fout:
                    shutil.copyfileobj(fin, fout)

            # Atomic move into place
            self._atomic_replace(tmp_path, dst)
            self._chmod_600(dst)
        except Exception:
            # Cleanup temp on error
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _gzip_atomic(self, src: Path, dst: Path) -> None:
        """Gzip-compress src into dst atomically."""
        tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=dst.stem + "_", suffix=dst.suffix, dir=str(self.backup_dir))
        os.close(tmp_fd)
        tmp_path = Path(tmp_path_str)

        try:
            with open(src, "rb") as f_in, gzip.open(tmp_path, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

            self._atomic_replace(tmp_path, dst)
            self._chmod_600(dst)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _save_metadata(
        self,
        backup_path: Path,
        src_path: Path,
        description: Optional[str],
        *,
        checksum: Optional[str] = None,
    ) -> None:
        """Save backup metadata next to the backup file."""
        metadata = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": str(src_path.resolve()),
            "size_bytes": backup_path.stat().st_size,
            "compressed": self.compress,
            "description": description,
        }
        if checksum:
            metadata["sha256"] = checksum

        meta_path = self._metadata_path_for(backup_path)
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            _log.warning("backup_metadata_write_failed", extra={"path": str(meta_path), "error": str(e)})

    def _read_metadata_for(self, backup_path: Path) -> Optional[Dict[str, Any]]:
        """Read metadata next to the given backup file."""
        meta_path = self._metadata_path_for(backup_path)
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            _log.warning("backup_metadata_read_failed", extra={"path": str(meta_path), "error": str(e)})
            return None

    def _rotate(self) -> None:
        """Apply retention policy: by days and/or keep_last count."""
        backups = list(self._iter_backup_files())
        backups.sort(key=lambda p: p.stat().st_mtime)  # oldest first

        # 1) Remove by age (keep_days)
        if self.keep_days > 0:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=self.keep_days)
            cutoff_ts = cutoff_dt.timestamp()

            for b in list(backups):
                mtime = b.stat().st_mtime
                meta = self._read_metadata_for(b)
                # Prefer metadata timestamp if available
                if meta and "timestamp" in meta:
                    try:
                        mtime = datetime.fromisoformat(meta["timestamp"]).timestamp()
                    except Exception:
                        pass

                if mtime < cutoff_ts:
                    self._delete_backup_with_meta(b)
                    backups.remove(b)

        # 2) Remove by count (keep_last)
        if self.keep_last is not None and self.keep_last >= 0:
            overflow = max(0, len(backups) - self.keep_last)
            for b in backups[:overflow]:
                self._delete_backup_with_meta(b)

    def _delete_backup_with_meta(self, backup_file: Path) -> None:
        """Delete backup file and its metadata sidecar."""
        try:
            backup_file.unlink(missing_ok=True)
            meta = self._metadata_path_for(backup_file)
            if meta.exists():
                meta.unlink(missing_ok=True)
            _log.info("backup_rotated", extra={"file": str(backup_file)})
        except Exception as e:
            _log.warning("backup_rotate_delete_failed", extra={"file": str(backup_file), "error": str(e)})

    # ------------- utils -------------

    def _iter_backup_files(self):
        # Match both .sqlite3 and .sqlite3.gz
        yield from self.backup_dir.glob("*.sqlite3")
        yield from self.backup_dir.glob("*.sqlite3.gz")

    @staticmethod
    def _metadata_path_for(backup_path: Path) -> Path:
        """
        Return sidecar metadata path.
        For *.sqlite3.gz → *.sqlite3.json
        For *.sqlite3     → *.sqlite3.json
        """
        if backup_path.suffix == ".gz":
            # replace .gz with .json (keeping .sqlite3)
            return backup_path.with_suffix("").with_suffix(".json")
        return backup_path.with_suffix(".json")

    @staticmethod
    def _atomic_replace(tmp_path: Path, final_path: Path) -> None:
        """Atomically move tmp_path to final_path (replace if exists)."""
        # Ensure parent dir exists
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, final_path)

    @staticmethod
    def _chmod_600(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except Exception:
            # best effort on non-POSIX or restricted FS
            pass

    @staticmethod
    def _sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()


# Legacy function for compatibility
def backup_database(src_path: str, backup_dir: str = "./backups") -> str:
    """Legacy backup function for compatibility (no compression)."""
    backup_mgr = DatabaseBackup(backup_dir=backup_dir, compress=False)
    return backup_mgr.backup(src_path)
