# src/crypto_ai_bot/core/storage/__init__.py
from __future__ import annotations

# Базовые экспортируемые символы
from .sqlite_adapter import connect, SqliteUnitOfWork  # type: ignore
try:
    from .sqlite_adapter import get_db_stats  # type: ignore
except Exception:
    # не критично — просто не экспортируем, если нет
    pass
try:
    from .sqlite_adapter import perform_maintenance  # type: ignore
except Exception:
    # не критично — просто не экспортируем, если нет
    pass

# Унификация имени транзакционного контекст-менеджера: in_txn
# Поддерживаем альтернативы (in_transaction, transaction), а при отсутствии даём безопасный fallback.
try:
    from .sqlite_adapter import in_txn  # type: ignore
except Exception:
    try:
        from .sqlite_adapter import in_transaction as in_txn  # type: ignore
    except Exception:
        try:
            from .sqlite_adapter import transaction as in_txn  # type: ignore
        except Exception:
            # Fallback: минимальный контекст-менеджер транзакции для sqlite3.Connection
            from contextlib import contextmanager

            @contextmanager
            def in_txn(conn):
                cur = conn.cursor()
                try:
                    cur.execute("BEGIN")
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    cur.close()

__all__ = [name for name in (
    "connect",
    "SqliteUnitOfWork",
    "get_db_stats",
    "perform_maintenance",
    "in_txn",
) if name in globals()]
