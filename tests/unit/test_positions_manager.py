# tests/unit/test_positions_manager.py
from __future__ import annotations
from contextlib import nullcontext
from decimal import Decimal
from typing import Optional, Dict, Any, List

from crypto_ai_bot.core.positions.manager import PositionManager


# ── фейковые реализации репозиториев/UnitOfWork ──────────────────────────────
class FakeUOW:
    """Фейковый UnitOfWork"""
    def transaction(self):
        return nullcontext()


class FakePositions:
    """Фейковый репозиторий позиций"""
    def __init__(self):
        self._pos = {}  # symbol -> dict

    def get_open(self) -> List[Dict[str, Any]]:
        """Возвращает список открытых позиций"""
        return list(self._pos.values())
    
    def get_open_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Возвращает позицию по символу"""
        return self._pos.get(symbol)

    def upsert(self, position: dict) -> None:
        """Сохраняет или обновляет позицию"""
        self._pos[position["symbol"]] = position
    
    def save(self, position: dict) -> None:
        """Алиас для upsert"""
        self.upsert(position)


class FakeTrades:
    """Фейковый репозиторий сделок"""
    def __init__(self):
        self.items: List[Dict[str, Any]] = []

    def insert(self, trade: Dict[str, Any]) -> None:
        """Добавляет сделку"""
        self.items.append(trade)

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Возвращает сделки по символу"""
        return [t for t in self.items if t.get("symbol") == symbol][-limit:]


class FakeAudit:
    """Фейковый репозиторий аудита"""
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def record(self, event: Dict[str, Any]) -> None:
        """Записывает событие аудита"""
        self.events.append(event)


def test_open_add_reduce_close_flow():
    """Тест полного цикла работы с позицией"""
    pm = PositionManager(
        positions_repo=FakePositions(),
        trades_repo=FakeTrades(),
        audit_repo=FakeAudit(),
        uow=FakeUOW(),
    )

    sym = "BTC/USDT"

    # Открытие позиции
    snap = pm.open_or_add(sym, Decimal("0.01000000"), Decimal("50000"))
    assert snap["symbol"] == sym
    assert snap["size"] == "0.01000000"
    assert snap["avg_price"] == "50000.00000000"

    # Добавление к позиции
    snap = pm.open_or_add(sym, Decimal("0.02000000"), Decimal("51000"))
    assert snap["size"] == "0.03000000"
    # Средняя цена: (0.01 * 50000 + 0.02 * 51000) / 0.03 = 50666.666...
    avg_price = float(snap["avg_price"])
    assert abs(avg_price - 50666.6666) < 1.0, f"Expected ~50666.67, got {avg_price}"

    # Частичное закрытие (reduce теперь не требует цену)
    snap = pm.reduce(sym, Decimal("0.005"))
    assert snap["size"].startswith("0.025")  # 0.03 - 0.005 = 0.025
    # Средняя цена должна остаться той же после частичного закрытия
    assert abs(float(snap["avg_price"]) - 50666.6666) < 1.0

    # Полное закрытие
    snap = pm.close_all(sym)
    assert snap["size"] == "0.00000000"
    assert snap["avg_price"] == "0.00000000"


def test_reduce_without_position():
    """Тест уменьшения несуществующей позиции"""
    pm = PositionManager(
        positions_repo=FakePositions(),
        trades_repo=FakeTrades(),
        audit_repo=FakeAudit(),
        uow=FakeUOW(),
    )

    # Попытка уменьшить несуществующую позицию
    snap = pm.reduce("ETH/USDT", Decimal("0.1"))
    assert snap["symbol"] == "ETH/USDT"
    assert snap["size"] == "0.00000000"
    assert snap["avg_price"] == "0.00000000"


def test_close_without_position():
    """Тест закрытия несуществующей позиции"""
    pm = PositionManager(
        positions_repo=FakePositions(),
        trades_repo=FakeTrades(),
        audit_repo=FakeAudit(),
        uow=FakeUOW(),
    )

    # Попытка закрыть несуществующую позицию
    snap = pm.close_all("ETH/USDT")
    assert snap["symbol"] == "ETH/USDT"
    assert snap["size"] == "0.00000000"
    assert snap["avg_price"] == "0.00000000"


def test_multiple_positions():
    """Тест работы с несколькими позициями"""
    pm = PositionManager(
        positions_repo=FakePositions(),
        trades_repo=FakeTrades(),
        audit_repo=FakeAudit(),
        uow=FakeUOW(),
    )

    # Открываем позицию по BTC
    btc_snap = pm.open_or_add("BTC/USDT", Decimal("0.01"), Decimal("50000"))
    assert btc_snap["size"] == "0.01000000"

    # Открываем позицию по ETH
    eth_snap = pm.open_or_add("ETH/USDT", Decimal("0.5"), Decimal("3000"))
    assert eth_snap["size"] == "0.50000000"
    assert eth_snap["avg_price"] == "3000.00000000"

    # Добавляем к BTC
    btc_snap = pm.open_or_add("BTC/USDT", Decimal("0.01"), Decimal("51000"))
    assert btc_snap["size"] == "0.02000000"
    # Средняя цена BTC: (0.01 * 50000 + 0.01 * 51000) / 0.02 = 50500
    assert abs(float(btc_snap["avg_price"]) - 50500) < 1.0

    # ETH позиция не должна быть затронута
    eth_snap = pm.reduce("ETH/USDT", Decimal("0.1"))
    assert eth_snap["size"] == "0.40000000"