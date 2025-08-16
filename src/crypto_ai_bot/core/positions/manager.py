# src/crypto_ai_bot/core/positions/manager.py
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.storage.interfaces import PositionRepository, TradeRepository, AuditRepository, UnitOfWork
from crypto_ai_bot.core.storage.sqlite_adapter import now_ms


class PositionManager:
    """Управляет агрегированной позицией по символу.
    Никаких прямых SQL — только вызовы репозиториев.
    """

    def __init__(
        self,
        *,
        positions_repo: PositionRepository,
        trades_repo: TradeRepository,
        audit_repo: AuditRepository,
        uow: UnitOfWork,
    ) -> None:
        self._positions = positions_repo
        self._trades = trades_repo
        self._audit = audit_repo
        self._uow = uow

    def _get_pos(self, symbol: str) -> Dict[str, Any]:
        cur = self._positions.get_open_by_symbol(symbol)
        return cur or {"symbol": symbol, "size": "0", "avg_price": "0", "updated_ts": now_ms()}

    def snapshot(self, symbol: str) -> Dict[str, Any]:
        return self._get_pos(symbol)

    def exposure(self, symbol: str) -> Decimal:
        p = self._get_pos(symbol)
        return Decimal(str(p["size"]))

    def open_or_add(self, symbol: str, qty: Decimal, price: Decimal) -> Dict[str, Any]:
        """Увеличение позиции по средневзвешенной цене."""
        with self._uow.transaction():
            p = self._get_pos(symbol)
            cur_qty = Decimal(str(p["size"]))
            cur_avg = Decimal(str(p["avg_price"]))
            new_qty = cur_qty + qty
            if new_qty <= 0:
                # позиция закрыта
                self._positions.upsert({"symbol": symbol, "size": "0", "avg_price": "0", "updated_ts": now_ms()})
                self._audit.record({"type": "position_closed", "symbol": symbol, "ts": now_ms()})
                return {"symbol": symbol, "size": "0", "avg_price": "0", "updated_ts": now_ms()}
            # новая средневзвешенная
            new_avg = ((cur_qty * cur_avg) + (qty * price)) / new_qty if cur_qty > 0 else price
            self._positions.upsert(
                {"symbol": symbol, "size": str(new_qty), "avg_price": str(new_avg), "updated_ts": now_ms()}
            )
            self._audit.record(
                {"type": "position_changed", "symbol": symbol, "amount": str(qty), "price": str(price), "ts": now_ms()}
            )
            return {"symbol": symbol, "size": str(new_qty), "avg_price": str(new_avg), "updated_ts": now_ms()}

    def reduce(self, symbol: str, qty: Decimal) -> Dict[str, Any]:
        """Частичное закрытие позиции."""
        with self._uow.transaction():
            p = self._get_pos(symbol)
            cur_qty = Decimal(str(p["size"]))
            new_qty = max(Decimal("0"), cur_qty - qty)
            self._positions.upsert(
                {"symbol": symbol, "size": str(new_qty), "avg_price": str(p["avg_price"]), "updated_ts": now_ms()}
            )
            self._audit.record({"type": "position_changed", "symbol": symbol, "amount": str(-qty), "ts": now_ms()})
            return self._get_pos(symbol)

    def close_all(self, symbol: str) -> Dict[str, Any]:
        with self._uow.transaction():
            self._positions.upsert({"symbol": symbol, "size": "0", "avg_price": "0", "updated_ts": now_ms()})
            self._audit.record({"type": "position_closed", "symbol": symbol, "ts": now_ms()})
            return self._get_pos(symbol)
