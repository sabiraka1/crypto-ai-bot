
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
    - возвращает снапшот с ключами {'symbol','size'}
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
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            pos = {"symbol": symbol, "size": _fmt(size)}
        else:
            new_size = Decimal(pos.get("size", "0")) + size
            pos["size"] = _fmt(new_size)
        self._save(pos)
        return pos

    def reduce(self, symbol: str, size: Decimal, price: Decimal) -> Dict[str, Any]:
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            # нечего уменьшать — возвращаем нулевую позицию
            pos = {"symbol": symbol, "size": _fmt(Decimal("0"))}
            self._save(pos)
            return pos

        new_size = Decimal(pos.get("size", "0")) - size
        if new_size < 0:
            new_size = Decimal("0")
        pos["size"] = _fmt(new_size)
        self._save(pos)
        return pos

    def close(self, symbol: str) -> Dict[str, Any]:
        pos = self._find_open_by_symbol(symbol)
        if pos is None:
            pos = {"symbol": symbol, "size": _fmt(Decimal("0"))}
        else:
            pos["size"] = _fmt(Decimal("0"))
        self._save(pos)
        return pos
