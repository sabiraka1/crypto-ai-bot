from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

DEC_Q = Decimal("0.00000001")

def _fmt(d: Decimal) -> str:
    return str(d.quantize(DEC_Q, rounding=ROUND_DOWN))

class PositionManager:
    """
    Упрощённый менеджер позиций под unit-тест:
    - хранит агрегированную позицию по символу (size как строка с 8 знаками)
    - рассчитывает среднюю цену входа (avg_price)
    - возвращает снапшот с ключами {'symbol','size','avg_price'}
    - использует репозиторий, если тот предоставляет нужные методы, но может работать и без него
    """

    def __init__(
        self,
        *,
        positions_repo=None,
        trades_repo=None,
        audit_repo=None,
        uow=None,
    ) -> None:
        self.positions_repo = positions_repo
        self.trades_repo = trades_repo
        self.audit_repo = audit_repo
        self.uow = uow
        # внутренний стор для случая отсутствия реального репозитория
        self._mem: Dict[str, Dict[str, Any]] = {}
        # история сделок для расчета средней цены
        self._trades_history: Dict[str, List[Dict[str, Decimal]]] = {}

    # --- helpers --------------------------------------------------------
    def _find_open_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        # сначала репозиторий
        repo = self.positions_repo
        if repo is not None and hasattr(repo, "get_open"):
            try:
                items = repo.get_open()
            except Exception:
                items = None
            if items is None:
                items = []
            for p in items:
                if isinstance(p, dict) and p.get("symbol") == symbol and Decimal(p.get("size", "0")) > 0:
                    return p

        # затем память
        pos = self._mem.get(symbol)
        if pos and Decimal(pos.get("size", "0")) > 0:
            return pos
        return None

    def _calculate_avg_price(self, symbol: str) -> Decimal:
        """Рассчитывает средневзвешенную цену для позиции"""
        trades = self._trades_history.get(symbol, [])
        if not trades:
            return Decimal("0")
        
        total_value = Decimal("0")
        total_size = Decimal("0")
        
        for trade in trades:
            size = trade.get("size", Decimal("0"))
            price = trade.get("price", Decimal("0"))
            total_value += size * price
            total_size += size
        
        if total_size == 0:
            return Decimal("0")
        
        return total_value / total_size

    def _save(self, pos: Dict[str, Any]) -> None:
        symbol = pos["symbol"]
        self._mem[symbol] = pos
        repo = self.positions_repo
        if repo is not None:
            if hasattr(repo, "upsert"):
                try:
                    repo.upsert(pos)
                except Exception:
                    pass
            elif hasattr(repo, "save"):
                try:
                    repo.save(pos)
                except Exception:
                    pass

    # --- public API -----------------------------------------------------
    def open_or_add(self, symbol: str, size: Decimal, price: Decimal) -> Dict[str, Any]:
        """Открытие или добавление к позиции"""
        pos = self._find_open_by_symbol(symbol)
        
        # Добавляем сделку в историю
        if symbol not in self._trades_history:
            self._trades_history[symbol] = []
        self._trades_history[symbol].append({"size": size, "price": price})
        
        if pos is None:
            # Новая позиция
            pos = {
                "symbol": symbol, 
                "size": _fmt(size),
                "avg_price": _fmt(price)
            }
        else:
            # Добавление к существующей
            new_size = Decimal(pos.get("size", "0")) + size
            pos["size"] = _fmt(new_size)
            # Пересчитываем среднюю цену
            pos["avg_price"] = _fmt(self._calculate_avg_price(symbol))
        
        self._save(pos)
        return pos

    def reduce(self, symbol: str, size: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        """Уменьшение позиции"""
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            # нечего уменьшать — возвращаем нулевую позицию
            pos = {"symbol": symbol, "size": _fmt(Decimal("0")), "avg_price": _fmt(Decimal("0"))}
            self._save(pos)
            return pos

        new_size = Decimal(pos.get("size", "0")) - size
        if new_size <= 0:
            new_size = Decimal("0")
            # Очищаем историю сделок при закрытии позиции
            if symbol in self._trades_history:
                del self._trades_history[symbol]
            pos["avg_price"] = _fmt(Decimal("0"))
        else:
            # Корректируем историю сделок пропорционально
            if symbol in self._trades_history:
                reduction_ratio = size / Decimal(pos.get("size", "1"))
                for trade in self._trades_history[symbol]:
                    trade["size"] = trade["size"] * (1 - reduction_ratio)
            pos["avg_price"] = _fmt(self._calculate_avg_price(symbol))
        
        pos["size"] = _fmt(new_size)
        self._save(pos)
        return pos

    def close(self, symbol: str) -> Dict[str, Any]:
        """Полное закрытие позиции"""
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            pos = {"symbol": symbol, "size": _fmt(Decimal("0")), "avg_price": _fmt(Decimal("0"))}
        else:
            pos["size"] = _fmt(Decimal("0"))
            pos["avg_price"] = _fmt(Decimal("0"))
            # Очищаем историю сделок
            if symbol in self._trades_history:
                del self._trades_history[symbol]
        
        self._save(pos)
        return pos

    def close_all(self, symbol: str) -> Dict[str, Any]:
        """Полное закрытие позиции (алиас для close)"""
        return self.close(symbol)
        """Полное закрытие позиции"""
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            pos = {"symbol": symbol, "size": _fmt(Decimal("0")), "avg_price": _fmt(Decimal("0"))}
        else:
            pos["size"] = _fmt(Decimal("0"))
            pos["avg_price"] = _fmt(Decimal("0"))
            # Очищаем историю сделок
            if symbol in self._trades_history:
                del self._trades_history[symbol]
        
        self._save(pos)
        return pos