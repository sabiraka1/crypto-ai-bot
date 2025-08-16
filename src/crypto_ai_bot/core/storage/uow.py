from __future__ import annotations
import sqlite3
from .interfaces import UnitOfWork

class SqliteUnitOfWork(UnitOfWork):
    """
    UnitOfWork с контекстным менеджером:
        with SqliteUnitOfWork(con) as tx:
            # ... репозитории через repos.*(tx)
            tx.commit()  # по текущему контракту place_order(...)
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con
        self._active = False

    # --- контекстный протокол ---
    def __enter__(self):
        self.begin()
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self._active = False
        # не подавляем исключения
        return False  # type: ignore[return-value]

    # --- явные операции ---
    def begin(self) -> None:
        self._con.execute("BEGIN IMMEDIATE;")

    def commit(self) -> None:
        self._con.commit()

    def rollback(self) -> None:
        self._con.rollback()
