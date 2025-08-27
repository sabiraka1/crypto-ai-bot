from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# репозитории
from .repositories.trades import TradesRepo
from .repositories.positions import PositionsRepo
from .repositories.market_data import MarketDataRepo
from .repositories.audit import AuditRepo
from .repositories.idempotency import IdempotencyRepo


@dataclass
class Storage:
    conn: sqlite3.Connection
    trades: TradesRepo
    positions: PositionsRepo
    market_data: MarketDataRepo
    audit: AuditRepo
    idempotency: IdempotencyRepo

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Storage":
        conn.row_factory = sqlite3.Row
        return cls(
            conn=conn,
            trades=TradesRepo(conn),
            positions=PositionsRepo(conn),
            market_data=MarketDataRepo(conn),
            audit=AuditRepo(conn),
            idempotency=IdempotencyRepo(conn),
        )

    @classmethod
    def open(cls, db_path: str, *, now_ms: int) -> "Storage":
        """Открытие БД + миграции (импорт мигратора внутри, чтобы app не тянул internals)."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # локальный импорт, чтобы не нарушать импорт-контракты в app-слое
        from .migrations.runner import run_migrations  # type: ignore

        run_migrations(conn, now_ms=now_ms, db_path=db_path)
        return cls.from_connection(conn)
