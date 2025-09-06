"""Database maintenance CLI utility.

Located in cli layer - provides backup, vacuum, integrity check operations.
Supports automated rotation and comprehensive health checks.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from crypto_ai_bot.core.infrastructure.settings import get_settings
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Configuration ==============

class MaintenanceConfig:
    """Maintenance configuration."""

    def __init__(self, settings: Any):
        self.db_path = Path(getattr(settings, "DB_PATH", "./data/trader.sqlite3"))
        self.backups_dir = Path(getattr(settings, "BACKUPS_DIR", "./backups"))
        self.retention_days = int(getattr(settings, "BACKUP_RETENTION_DAYS", 7))
        self.compress_backups = bool(getattr(settings, "COMPRESS_BACKUPS", True))
        self.max_backup_size_mb = int(getattr(settings, "MAX_BACKUP_SIZE_MB", 1000))

    def validate(self) -> None:
        """Validate configuration for operations that require live DB."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        if self.retention_days < 1:
            raise ValueError(f"Invalid retention days: {self.retention_days}")


# ============== Database Operations ==============

class DatabaseMaintenance:
    """Database maintenance operations."""

    def __init__(self, config: MaintenanceConfig):
        self.config = config
        self._trace_id = generate_trace_id()

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        """Create database connection with sane defaults."""
        uri = f"file:{self.config.db_path}"
        uri += "?mode=ro" if readonly else "?mode=rw"

        conn = sqlite3.connect(uri, uri=True, timeout=15.0)  # busy timeout at API level
        conn.row_factory = sqlite3.Row

        # Pragmas (safe defaults)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
        except sqlite3.DatabaseError:
            pass

        return conn

    def backup(self, description: Optional[str] = None) -> Path:
        """Create database backup (consistent snapshot via sqlite3 backup API)."""
        # Ensure backups directory exists
        self.config.backups_dir.mkdir(parents=True, exist_ok=True)

        # Generate backup filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_name = f"db-{timestamp}"

        if description:
            # Sanitize description for filename
            safe_desc = "".join(c if c.isalnum() or c in "-_" else "_" for c in description)
            backup_name += f"-{safe_desc}"

        # Build final paths
        raw_backup_path = self.config.backups_dir / f"{backup_name}.sqlite3"
        final_backup_path = (
            self.config.backups_dir / f"{backup_name}.sqlite3.gz"
            if self.config.compress_backups
            else raw_backup_path
        )

        try:
            _log.info(
                "backup_started",
                extra={
                    "source": str(self.config.db_path),
                    "destination": str(final_backup_path),
                    "trace_id": self._trace_id,
                },
            )

            # 1) Make consistent snapshot using sqlite backup API
            src = sqlite3.connect(f"file:{self.config.db_path}?mode=ro", uri=True, timeout=30.0)
            try:
                dst = sqlite3.connect(str(raw_backup_path), timeout=30.0)
                try:
                    dst.execute("PRAGMA journal_mode=OFF;")
                    # use pages=0 => all, progress callback optional
                    src.backup(dst)
                    dst.commit()
                finally:
                    dst.close()
            finally:
                src.close()

            # 2) Optionally compress
            if self.config.compress_backups:
                with open(raw_backup_path, "rb") as f_in, gzip.open(final_backup_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
                raw_backup_path.unlink(missing_ok=True)

            # 3) Check backup size
            size_mb = final_backup_path.stat().st_size / (1024 * 1024)
            if size_mb > self.config.max_backup_size_mb:
                _log.warning(
                    "backup_size_exceeded",
                    extra={
                        "size_mb": size_mb,
                        "max_mb": self.config.max_backup_size_mb,
                        "trace_id": self._trace_id,
                    },
                )

            # 4) Create metadata (sibling .json)
            metadata = {
                "timestamp": timestamp,
                "source": str(self.config.db_path),
                "size_bytes": final_backup_path.stat().st_size,
                "compressed": self.config.compress_backups,
                "description": description,
                "trace_id": self._trace_id,
            }

            # NOTE: we place metadata next to final artifact, with ".json"
            metadata_path = final_backup_path.with_suffix(".json")
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            _log.info(
                "backup_completed",
                extra={
                    "path": str(final_backup_path),
                    "size_mb": size_mb,
                    "trace_id": self._trace_id,
                },
            )

            print(f"✅ Backup created: {final_backup_path}")
            print(f"   Size: {size_mb:.2f} MB")

            return final_backup_path

        except Exception as e:
            _log.error(
                "backup_failed",
                exc_info=True,
                extra={"error": str(e), "trace_id": self._trace_id},
            )
            raise

    def rotate(self, retention_days: Optional[int] = None) -> int:
        """Rotate old backups."""
        if retention_days is None:
            retention_days = self.config.retention_days

        if not self.config.backups_dir.exists():
            print("✅ No backups to rotate")
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        removed_count = 0
        removed_size = 0

        # Find all backup files
        patterns = ["db-*.sqlite3", "db-*.sqlite3.gz"]
        backups: list[Path] = []
        for pattern in patterns:
            backups.extend(self.config.backups_dir.glob(pattern))

        for backup_path in backups:
            try:
                # Parse timestamp from filename
                stem = backup_path.stem.replace(".sqlite3", "")
                parts = stem.split("-")

                if len(parts) >= 3:
                    date_str = parts[1]
                    time_str = parts[2]

                    # Parse datetime
                    backup_dt = datetime.strptime(
                        f"{date_str}{time_str}", "%Y%m%d%H%M%S"
                    ).replace(tzinfo=timezone.utc)

                    # Check if should remove
                    if backup_dt < cutoff:
                        size = backup_path.stat().st_size

                        # Remove backup and metadata
                        backup_path.unlink(missing_ok=True)
                        metadata_path = backup_path.with_suffix(".json")
                        if metadata_path.exists():
                            metadata_path.unlink(missing_ok=True)

                        removed_count += 1
                        removed_size += size

                        _log.info(
                            "backup_rotated",
                            extra={
                                "path": str(backup_path),
                                "age_days": (datetime.now(timezone.utc) - backup_dt).days,
                                "trace_id": self._trace_id,
                            },
                        )

            except (ValueError, IndexError) as e:
                _log.warning(
                    "backup_parse_failed",
                    extra={
                        "path": str(backup_path),
                        "error": str(e),
                        "trace_id": self._trace_id,
                    },
                )
                continue

        size_mb = removed_size / (1024 * 1024)
        print("✅ Rotation completed:")
        print(f"   Removed: {removed_count} backups")
        print(f"   Freed: {size_mb:.2f} MB")
        print(f"   Retention: {retention_days} days")

        return removed_count

    def vacuum(self) -> None:
        """Vacuum database to reclaim space."""
        conn = self._connect()

        try:
            # Get size before vacuum
            size_before = self.config.db_path.stat().st_size

            _log.info(
                "vacuum_started",
                extra={
                    "size_bytes": size_before,
                    "trace_id": self._trace_id,
                },
            )

            # Run vacuum
            conn.execute("VACUUM;")
            conn.execute("ANALYZE;")  # Update statistics
            conn.commit()

            # Get size after vacuum
            size_after = self.config.db_path.stat().st_size
            size_saved = size_before - size_after

            _log.info(
                "vacuum_completed",
                extra={
                    "size_before": size_before,
                    "size_after": size_after,
                    "size_saved": size_saved,
                    "trace_id": self._trace_id,
                },
            )

            size_saved_mb = size_saved / (1024 * 1024)
            print("✅ Vacuum completed:")
            print(f"   Size before: {size_before / (1024 * 1024):.2f} MB")
            print(f"   Size after: {size_after / (1024 * 1024):.2f} MB")
            print(f"   Saved: {size_saved_mb:.2f} MB")

        finally:
            conn.close()

    def check_integrity(self) -> bool:
        """Check database integrity."""
        conn = self._connect(readonly=True)

        try:
            _log.info("integrity_check_started", extra={"trace_id": self._trace_id})

            # Run integrity check
            cursor = conn.execute("PRAGMA integrity_check;")
            row = cursor.fetchone()
            result = row[0] if row else "unknown"

            is_ok = result == "ok"

            if is_ok:
                print("✅ Integrity check: PASSED")

                # Additional checks (best-effort)
                try:
                    cursor = conn.execute("PRAGMA foreign_key_check;")
                    fk_errors = cursor.fetchall()
                    if fk_errors:
                        print("⚠️  Foreign key violations found:")
                        for error in fk_errors[:10]:  # Limit output
                            # sqlite3.Row supports index/name access; guard keys
                            table = error["table"] if "table" in error.keys() else str(error[0])
                            rowid = error["rowid"] if "rowid" in error.keys() else str(error[1])
                            print(f"    Table: {table}, Row: {rowid}")
                        is_ok = False
                except sqlite3.DatabaseError:
                    pass

            else:
                print("❌ Integrity check: FAILED")
                print(f"   Error: {result}")

            _log.info(
                "integrity_check_completed",
                extra={
                    "result": result,
                    "ok": is_ok,
                    "trace_id": self._trace_id,
                },
            )

            return is_ok

        finally:
            conn.close()

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        conn = self._connect(readonly=True)

        try:
            stats: dict[str, Any] = {}

            # Database size
            stats["size_mb"] = self.config.db_path.stat().st_size / (1024 * 1024)

            # Table sizes via dbstat (best-effort)
            tables: list[dict[str, Any]] = []
            try:
                cursor = conn.execute(
                    """
                    SELECT name, SUM(pgsize) AS size
                    FROM dbstat
                    GROUP BY name
                    ORDER BY size DESC
                    LIMIT 10
                    """
                )
                for row in cursor:
                    name = row["name"] if "name" in row.keys() else str(row[0])
                    size = row["size"] if "size" in row.keys() else int(row[1])
                    tables.append({"name": name, "size_mb": float(size) / (1024 * 1024)})
            except sqlite3.DatabaseError:
                # dbstat may be unavailable; skip
                pass
            stats["tables"] = tables

            # Row counts for main tables (best-effort)
            main_tables = ["trades", "orders", "positions", "risk_counters"]
            row_counts: dict[str, int] = {}
            for table in main_tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                    row = cursor.fetchone()
                    row_counts[table] = int(row["cnt"] if row and "cnt" in row.keys() else (row[0] if row else 0))
                except sqlite3.OperationalError:
                    # Table doesn't exist
                    continue
            stats["row_counts"] = row_counts

            # Cache statistics (best-effort; pragma may not exist)
            try:
                cursor = conn.execute("PRAGMA cache_stats;")
                cache = cursor.fetchone()
                if cache:
                    stats["cache"] = dict(cache)
            except sqlite3.DatabaseError:
                pass

            return stats

        finally:
            conn.close()

    def list_backups(self) -> list[dict[str, Any]]:
        """List all backups with metadata."""
        if not self.config.backups_dir.exists():
            return []

        backups: list[dict[str, Any]] = []
        patterns = ["db-*.sqlite3", "db-*.sqlite3.gz"]

        for pattern in patterns:
            for backup_path in sorted(self.config.backups_dir.glob(pattern)):
                info: dict[str, Any] = {
                    "path": str(backup_path),
                    "name": backup_path.name,
                    "size_mb": backup_path.stat().st_size / (1024 * 1024),
                    "compressed": backup_path.suffix == ".gz",
                }

                # Try to load metadata
                metadata_path = backup_path.with_suffix(".json")
                if metadata_path.exists():
                    try:
                        with open(metadata_path, encoding="utf-8") as f:
                            metadata = json.load(f)
                            if isinstance(metadata, dict):
                                info.update(metadata)
                    except Exception:
                        pass

                # Parse timestamp from filename
                try:
                    stem = backup_path.stem.replace(".sqlite3", "")
                    parts = stem.split("-")
                    if len(parts) >= 3:
                        date_str = parts[1]
                        time_str = parts[2]
                        info["timestamp"] = f"{date_str}-{time_str}"

                        # Calculate age
                        backup_dt = datetime.strptime(
                            f"{date_str}{time_str}", "%Y%m%d%H%M%S"
                        ).replace(tzinfo=timezone.utc)
                        age = datetime.now(timezone.utc) - backup_dt
                        info["age_days"] = age.days

                except (ValueError, IndexError):
                    pass

                backups.append(info)

        return backups

    def restore(self, backup_file: Path) -> None:
        """Restore database from a backup (.sqlite3 or .sqlite3.gz)."""
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup not found: {backup_file}")

        # Prepare source temp path (handle .gz)
        if backup_file.suffix == ".gz":
            tmp_src = backup_file.with_suffix("")  # drop .gz
            with gzip.open(backup_file, "rb") as f_in, open(tmp_src, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            src_path = tmp_src
        else:
            src_path = backup_file

        # Validate source DB quickly
        try:
            conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=10.0)
            try:
                cur = conn.execute("PRAGMA integrity_check;")
                res = cur.fetchone()
                if not res or res[0] != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {res[0] if res else 'unknown'}")
            finally:
                conn.close()
        except Exception:
            # Clean temp if created
            if backup_file.suffix == ".gz":
                src_path.unlink(missing_ok=True)
            raise

        # Make safety copy of current DB
        if self.config.db_path.exists():
            safety = self.config.db_path.with_suffix(".current")
            shutil.copy2(self.config.db_path, safety)
            _log.info("restore_safety_backup_created", extra={"safety": str(safety), "trace_id": self._trace_id})

        # Replace DB
        shutil.copy2(src_path, self.config.db_path)

        # Cleanup temp decompressed file if any
        if backup_file.suffix == ".gz":
            src_path.unlink(missing_ok=True)

        print(f"✅ Restored DB from: {backup_file}")
        print(f"   Target: {self.config.db_path}")


# ============== CLI Commands ==============

def cmd_backup(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute backup command."""
    maintenance = DatabaseMaintenance(config)

    try:
        maintenance.backup(description=args.description)

        if args.rotate:
            maintenance.rotate()

        return 0

    except Exception as e:
        print(f"❌ Backup failed: {e}", file=sys.stderr)
        return 1


def cmd_rotate(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute rotate command."""
    maintenance = DatabaseMaintenance(config)

    try:
        removed = maintenance.rotate(retention_days=args.days)
        return 0 if removed >= 0 else 1

    except Exception as e:
        print(f"❌ Rotation failed: {e}", file=sys.stderr)
        return 1


def cmd_vacuum(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute vacuum command."""
    maintenance = DatabaseMaintenance(config)

    try:
        if args.backup_first:
            print("Creating backup before vacuum...")
            maintenance.backup(description="pre-vacuum")

        maintenance.vacuum()
        return 0

    except Exception as e:
        print(f"❌ Vacuum failed: {e}", file=sys.stderr)
        return 1


def cmd_integrity(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute integrity check command."""
    maintenance = DatabaseMaintenance(config)

    try:
        is_ok = maintenance.check_integrity()

        if args.stats:
            print("\n📊 Database Statistics:")
            stats = maintenance.get_stats()

            print(f"   Size: {stats.get('size_mb', 0):.2f} MB")

            if "row_counts" in stats and stats["row_counts"]:
                print("\n   Row counts:")
                for table, count in stats["row_counts"].items():
                    print(f"     {table}: {count:,}")

            if "tables" in stats and stats["tables"]:
                print("\n   Largest tables:")
                for table in stats["tables"][:5]:
                    print(f"     {table['name']}: {table['size_mb']:.2f} MB")

        return 0 if is_ok else 1

    except Exception as e:
        print(f"❌ Integrity check failed: {e}", file=sys.stderr)
        return 1


def cmd_list(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute list backups command."""
    maintenance = DatabaseMaintenance(config)

    try:
        backups = maintenance.list_backups()

        if not backups:
            print("No backups found")
            return 0

        print(f"📦 Backups ({len(backups)} total):\n")

        # Sort by age (youngest first)
        backups.sort(key=lambda x: x.get("age_days", 999))

        for backup in backups:
            print(f"  {backup['name']}")
            print(f"    Size: {backup['size_mb']:.2f} MB")

            if "age_days" in backup:
                print(f"    Age: {backup['age_days']} days")

            if backup.get("description"):
                print(f"    Description: {backup['description']}")

            if backup.get("compressed"):
                print("    Compressed: Yes")

            print()

        # Summary
        total_size = sum(float(b.get("size_mb", 0)) for b in backups)
        print(f"Total size: {total_size:.2f} MB")

        return 0

    except Exception as e:
        print(f"❌ List failed: {e}", file=sys.stderr)
        return 1


def cmd_restore(args: argparse.Namespace, config: MaintenanceConfig) -> int:
    """Execute restore command."""
    maintenance = DatabaseMaintenance(config)

    try:
        maintenance.restore(Path(args.backup))
        return 0
    except Exception as e:
        print(f"❌ Restore failed: {e}", file=sys.stderr)
        return 1


# ============== Main Entry Point ==============

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="cab-maintenance",
        description="Database maintenance utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create database backup")
    backup_parser.add_argument("--description", help="Backup description (included in filename)")
    backup_parser.add_argument("--rotate", action="store_true", help="Rotate old backups after creating new one")

    # Rotate command
    rotate_parser = subparsers.add_parser("rotate", help="Remove old backups")
    rotate_parser.add_argument("--days", type=int, help="Retention period in days (default from settings)")

    # Vacuum command
    vacuum_parser = subparsers.add_parser("vacuum", help="Vacuum database")
    vacuum_parser.add_argument("--backup-first", action="store_true", help="Create backup before vacuum")

    # Integrity command
    integrity_parser = subparsers.add_parser("integrity", help="Check database integrity")
    integrity_parser.add_argument("--stats", action="store_true", help="Show database statistics")

    # List command
    subparsers.add_parser("list", help="List backups")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("backup", help="Backup file to restore (.sqlite3 or .sqlite3.gz)")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    try:
        # Parse arguments
        args = parse_args(argv)

        # Load settings and config
        settings = get_settings()
        config = MaintenanceConfig(settings)

        # Validate only for commands that require live DB
        if args.command in {"backup", "vacuum", "integrity", "restore"}:
            config.validate()

        # Execute command
        commands = {
            "backup": cmd_backup,
            "rotate": cmd_rotate,
            "vacuum": cmd_vacuum,
            "integrity": cmd_integrity,
            "list": cmd_list,
            "restore": cmd_restore,
        }

        command_func = commands.get(args.command)
        if not command_func:
            print(f"❌ Unknown command: {args.command}", file=sys.stderr)
            return 1

        return command_func(args, config)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130

    except Exception as e:
        _log.error("maintenance_error", exc_info=True)
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
