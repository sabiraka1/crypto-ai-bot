from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ...utils.time import now_ms
from ...utils.logging import get_logger
from ..brokers.base import IBroker
from ..storage.facade import Storage


@dataclass
class DeadMansSwitch:
    """
    Простой DMS: если heartbeat не обновлялся дольше timeout_ms —
    пытаемся аварийно закрыть позицию (market sell base).
    Таблица heartbeats создаётся лениво.
    """
    storage: Storage
    broker: IBroker
    component: str = "orchestrator"
    timeout_ms: int = 120_000  # 2 минуты

    def __post_init__(self) -> None:
        self._log = get_logger("safety.dms")
        self._ensure_table()

    def beat(self) -> None:
        with self.storage.conn:
            self.storage.conn.execute(
                """
                INSERT INTO heartbeats(component, last_beat_ms, status)
                VALUES (?, ?, 'ok')
                ON CONFLICT(component) DO UPDATE SET last_beat_ms = excluded.last_beat_ms, status = 'ok'
                """,
                (self.component, now_ms()),
            )

    async def check_and_trigger(self, *, symbol: str) -> None:
        row = self.storage.conn.execute(
            "SELECT last_beat_ms FROM heartbeats WHERE component = ?", (self.component,)
        ).fetchone()

        last = int(row[0]) if row else 0
        if now_ms() - last <= self.timeout_ms:
            return  # всё ок

        # TIMEOUT — аварийное закрытие, если есть позиция
        pos = self.storage.positions.get_position(symbol)
        base = Decimal(pos.base_qty or 0)
        if base > 0:
            self._log.error("dms_timeout_emergency_close", extra={"symbol": symbol, "base_qty": str(base)})
            try:
                await self.broker.create_market_sell_base(symbol=symbol, amount_base=base)
            except Exception as exc:
                self._log.error("dms_close_failed", extra={"error": str(exc)})

    def _ensure_table(self) -> None:
        with self.storage.conn:
            self.storage.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS heartbeats (
                    component TEXT PRIMARY KEY,
                    last_beat_ms INTEGER NOT NULL,
                    status TEXT
                )
                """
            )
