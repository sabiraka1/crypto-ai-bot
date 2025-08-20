#!/usr/bin/env python3
# scripts/maintenance_cli.py
"""
Единый CLI для техобслуживания:
- cleanup: удаляет просроченные idempotency-ключи (по TTL)
- vacuum: checkpoint + VACUUM + ANALYZE/optimize
- backup: атомарный бэкап SQLite через встроенный API
- full: cleanup -> vacuum -> backup

Никаких прямых os.environ в домене — работаем через Settings.
Скрипт осторожно обращается к репозиториям: если у SqliteIdempotencyRepository
нет метода cleanup_expired(...), делает безопасный raw-SQL по обнаруженной схеме.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --- настройки/логи ---
try:
    from crypto_ai_bot.core.settings import Settings
except Exception as e:  # не должно происходить, но пусть будет человеко-читаемо
    print(f"[maintenance] cannot import Settings: {e}", file=sys.stderr)
    sys.exit(2)

try:
    from crypto_ai_bot.utils.logging import get_logger
    log = get_logger("maintenance")
except Exception:
    # very light fallback
    class _L:
        def info(self, *a, **k): print("[INFO]", *a, **k, file=sys.stdout)
        def warning(self, *a, **k): print("[WARN]", *a, **k, file=sys.stdout)
        def error(self, *a, **k): print("[ERROR]", *a, **k, file=sys.stderr)
        def exception(self, *a, **k): print("[EXC]", *a, **k, file=sys.stderr)
    log = _L()

# --- подключение SQLite (единый адаптер проекта) ---
try:
    from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect
except Exception:
    # очень компактный фолбэк
    def sqlite_connect(path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

# --- репозитории (опционально) ---
IdRepoCls = None
try:
    from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository as IdRepoCls  # type: ignore
except Exception:
    IdRepoCls = None


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def cleanup_idempotency(conn: sqlite3.Connection, ttl_sec: int) -> int:
    """
    Удалить протухшие ключи идемпотентности.
    1) если в репозитории есть официальный метод cleanup_expired(ttl_sec) — используем его
    2) иначе — аккуратный raw-SQL:
       - если есть expires_at_ms: удаляем где expires_at_ms <= now
       - иначе если есть created_ms: удаляем где created_ms <= now - ttl
    Возвращает количество удалённых записей (если удалось узнать).
    """
    # 1) официальный репозиторий
    if IdRepoCls is not None:
        try:
            repo = IdRepoCls(conn)
            if hasattr(repo, "cleanup_expired"):
                removed = repo.cleanup_expired(ttl_sec=ttl_sec)  # type: ignore[arg-type]
                if removed is None:
                    removed = -1
                log.info("cleanup_idempotency(repo): removed=%s", removed)
                return int(removed)
        except Exception:
            log.exception("cleanup_idempotency(repo) failed; fallback to raw SQL")

    # 2) raw SQL — обнаружим схему
    now_ms = _now_ms()
    cutoff_ms = now_ms - int(ttl_sec) * 1000
    try:
        cur = conn.cursor()
        # найдём имя таблицы (обычно 'idempotency'); если неизвестно — пробуем несколько
        candidate_tables = ("idempotency", "idempotency_keys", "idem")
        table_name = None
        for t in candidate_tables:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,))
            if cur.fetchone():
                table_name = t
                break
        if not table_name:
            log.warning("idempotency table not found; skip cleanup")
            return 0

        # проверим колонки
        cur.execute(f"PRAGMA table_info({table_name})")
        cols = {row[1] for row in cur.fetchall()}  # type: ignore[index]

        removed = 0
        if "expires_at_ms" in cols:
            cur.execute(f"DELETE FROM {table_name} WHERE expires_at_ms <= ?", (now_ms,))
            removed = cur.rowcount if cur.rowcount is not None else -1
        elif "created_ms" in cols:
            cur.execute(f"DELETE FROM {table_name} WHERE created_ms <= ?", (cutoff_ms,))
            removed = cur.rowcount if cur.rowcount is not None else -1
        else:
            log.warning("Unknown idempotency schema (no expires_at_ms/created_ms); skip cleanup")
            return 0

        conn.commit()
        log.info("cleanup_idempotency(raw): removed=%s", removed)
        return int(removed)
    except Exception:
        log.exception("cleanup_idempotency(raw) failed")
        return 0


def vacuum_optimize(conn: sqlite3.Connection) -> None:
    """
    Чистка и оптимизация:
    - checkpoint WAL → TRUNCATE
    - VACUUM (сжатие)
    - ANALYZE + PRAGMA optimize
    """
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        cur.execute("VACUUM;")
        cur.execute("ANALYZE;")
        cur.execute("PRAGMA optimize;")
        conn.commit()
        log.info("vacuum_optimize: ok")
    except Exception:
        log.exception("vacuum_optimize failed")


def backup_sqlite(db_path: str, backup_dir: Path) -> Path:
    """
    Атомарный бэкап с использованием SQLite backup API.
    Имя: <dbname>-YYYYmmddTHHMMSS.sqlite
    """
    _ensure_dir(backup_dir)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    base = Path(db_path).stem
    out = backup_dir / f"{base}-{ts}.sqlite"

    src = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    dst = sqlite3.connect(str(out), isolation_level=None, check_same_thread=False)
    try:
        with dst:
            src.backup(dst)  # атомарный снимок
        os.chmod(out, 0o600)
        log.info("backup_sqlite: created %s", out)
        return out
    finally:
        dst.close()
        src.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="crypto-ai-bot maintenance CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cleanup = sub.add_parser("cleanup", help="cleanup idempotency TTL")
    p_cleanup.add_argument("--ttl-sec", type=int, default=None, help="override TTL seconds")

    sub.add_parser("vacuum", help="checkpoint, VACUUM, ANALYZE/optimize")

    p_backup = sub.add_parser("backup", help="SQLite backup")
    p_backup.add_argument("--out-dir", type=str, default=None, help="backup directory")

    p_full = sub.add_parser("full", help="cleanup -> vacuum -> backup")
    p_full.add_argument("--ttl-sec", type=int, default=None, help="override TTL seconds")
    p_full.add_argument("--out-dir", type=str, default=None, help="backup directory")

    args = parser.parse_args()

    settings = Settings.load()
    db_path = getattr(settings, "DB_PATH", "/data/bot.sqlite")
    ttl_default = int(getattr(settings, "IDEMPOTENCY_TTL_SEC", getattr(settings, "IDEMPOTENCY_TTL_SECONDS", 900)))
    ttl_sec = int(getattr(args, "ttl_sec", None) or ttl_default)

    out_dir_arg = getattr(args, "out_dir", None)
    out_dir = Path(out_dir_arg) if out_dir_arg else Path(getattr(settings, "BACKUP_DIR", "/data/backups"))

    conn = sqlite_connect(db_path)

    try:
        if args.cmd == "cleanup":
            removed = cleanup_idempotency(conn, ttl_sec=ttl_sec)
            log.info("cleanup done: removed=%s", removed)
            return 0

        if args.cmd == "vacuum":
            vacuum_optimize(conn)
            return 0

        if args.cmd == "backup":
            backup_sqlite(db_path, out_dir)
            return 0

        if args.cmd == "full":
            removed = cleanup_idempotency(conn, ttl_sec=ttl_sec)
            log.info("cleanup done: removed=%s", removed)
            vacuum_optimize(conn)
            backup_sqlite(db_path, out_dir)
            return 0

        log.error("unknown command")
        return 2
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
