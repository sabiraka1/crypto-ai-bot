from __future__ import annotations
import sqlite3
from .interfaces import UnitOfWork

class SqliteUnitOfWork(UnitOfWork):
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con
    def begin(self) -> None: self._con.execute("BEGIN IMMEDIATE;")
    def commit(self) -> None: self._con.commit()
    def rollback(self) -> None: self._con.rollback()
