# tests/unit/test_positions_manager.py
from __future__ import annotations
from contextlib import nullcontext
from decimal import Decimal

from crypto_ai_bot.core.positions.manager import PositionManager
from crypto_ai_bot.core.storage.interfaces import PositionRepository, TradeRepository, AuditRepository, UnitOfWork, Trade


# ── фейковые реализации репозиториев/UnitOfWork ──────────────────────────────
class FakeUOW(UnitOfWork):
    def transaction(self):
        return nullcontext()


class FakePositions(PositionRepository):
    def __init__(self):
        self._pos = {}  # symbol -> dict

    def get_open_by_symbol(self, symbol: str):
        return self._pos.get(symbol)

    def upsert(self, position: dict) -> None:
        self._pos[position["symbol"]] = position


class FakeTrades(TradeRepository):
    def __init__(self):
        self.items: list[Trade] = []

    def insert(self, trade: Trade) -> None:
        self.items.append(trade)

    def list_by_symbol(self, symbol: str, limit: int = 100):
        return [t for t in self.items if t.symbol == symbol][-limit:]


class FakeAudit(AuditRepository):
    def __init__(self):
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


def test_open_add_reduce_close_flow():
    pm = PositionManager(
        positions_repo=FakePositions(),
        trades_repo=FakeTrades(),
        audit_repo=FakeAudit(),
        uow=FakeUOW(),
    )

    sym = "BTC/USDT"

    # открытия/добавления
    snap = pm.open_or_add(sym, Decimal("0.01000000"), Decimal("50000"))
    assert snap["symbol"] == sym
    assert snap["size"] == "0.01000000"

    snap = pm.open_or_add(sym, Decimal("0.02000000"), Decimal("51000"))
    assert snap["size"] == "0.03000000"
    # средняя цена между 50k и 51k с весами 0.01/0.02 = 50666.(6)
    assert abs(float(snap["avg_price"]) - 50666.6666) < 1.0

    # частичное закрытие
    snap = pm.reduce(sym, Decimal("0.005"))
    assert snap["size"].startswith("0.02")  # 0.025 осталось

    # полное закрытие
    snap = pm.close_all(sym)
    assert snap["size"] == "0"
    assert snap["avg_price"] == "0"
