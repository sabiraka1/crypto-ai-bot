from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, List, Protocol

# Unit of Work protocol (узкая зависимость)
try:
    from crypto_ai_bot.core.storage.interfaces import UnitOfWork as UnitOfWork  # type: ignore
except Exception:
    class UnitOfWork(Protocol):
        def __enter__(self) -> Any: ...
        def __exit__(self, exc_type, exc, tb) -> None: ...


# Репозитории — узкие протоколы
class PositionsRepo(Protocol):
    def upsert(self, position: Dict[str, Any]) -> None: ...
    def get_open(self) -> Optional[List[Dict[str, Any]]]: ...
    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]: ...
    def close(self, pos_id: str) -> None: ...


class TradesRepo(Protocol):
    def insert(self, trade: Dict[str, Any]) -> None: ...


class AuditRepo(Protocol):
    def append(self, record: Dict[str, Any]) -> None: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_open_list(repo: PositionsRepo) -> List[Dict[str, Any]]:
    lst = repo.get_open()
    if lst is None:
        return []
    return lst


def _find_open_by_symbol(repo: PositionsRepo, symbol: str) -> Optional[Dict[str, Any]]:
    for p in _safe_open_list(repo):
        if p.get("symbol") == symbol and p.get("status") == "open":
            return p
    return None


@dataclass
class PositionManager:
    positions_repo: PositionsRepo
    trades_repo: Optional[TradesRepo] = None
    audit_repo: Optional[AuditRepo] = None
    uow: Optional[UnitOfWork] = None

    def open(self, symbol: str, side: str, size: Decimal, *, sl: Optional[Decimal] = None, tp: Optional[Decimal] = None) -> Dict[str, Any]:
        now = _now_iso()
        pos = {
            "id": f"pos-{symbol}-{now}",
            "symbol": symbol,
            "side": side,
            "qty": str(size),
            "sl": str(sl) if sl is not None else None,
            "tp": str(tp) if tp is not None else None,
            "status": "open",
            "opened_at": now,
        }
        if self.uow is not None:
            with self.uow:
                self.positions_repo.upsert(pos)
                if self.audit_repo:
                    self.audit_repo.append({"ts": now, "type": "position_open", "symbol": symbol, "side": side, "qty": str(size)})
        else:
            self.positions_repo.upsert(pos)
            if self.audit_repo:
                self.audit_repo.append({"ts": now, "type": "position_open", "symbol": symbol, "side": side, "qty": str(size)})
        return pos

    def open_or_add(self, symbol: str, qty: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Возвращает саму позицию (как ожидает тест), а не снимок.
        """
        side = "buy" if qty >= 0 else "sell"
        now = _now_iso()
        if self.uow is not None:
            with self.uow:
                pos = _find_open_by_symbol(self.positions_repo, symbol)
                if pos is None:
                    pos = self.open(symbol, side, abs(qty))
                else:
                    new_qty = (Decimal(str(pos.get("qty", "0"))) + abs(qty))
                    pos["qty"] = str(new_qty)
                    self.positions_repo.upsert(pos)
                if self.trades_repo:
                    self.trades_repo.insert({"ts": now, "symbol": symbol, "side": side, "price": str(price), "qty": str(abs(qty)), "action": "add"})
                if self.audit_repo:
                    self.audit_repo.append({"ts": now, "type": "order_add", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        else:
            pos = _find_open_by_symbol(self.positions_repo, symbol)
            if pos is None:
                pos = self.open(symbol, side, abs(qty))
            else:
                new_qty = (Decimal(str(pos.get("qty", "0"))) + abs(qty))
                pos["qty"] = str(new_qty)
                self.positions_repo.upsert(pos)
            if self.trades_repo:
                self.trades_repo.insert({"ts": now, "symbol": symbol, "side": side, "price": str(price), "qty": str(abs(qty)), "action": "add"})
            if self.audit_repo:
                self.audit_repo.append({"ts": now, "type": "order_add", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        return pos

    def reduce(self, symbol: str, qty: Decimal, price: Decimal) -> Dict[str, Any]:
        now = _now_iso()
        pos = _find_open_by_symbol(self.positions_repo, symbol)
        if pos is None:
            return {"status": "noop", "reason": "no_open_position"}

        cur_qty = Decimal(str(pos.get("qty", "0")))
        new_qty = cur_qty - abs(qty)
        if self.uow is not None:
            with self.uow:
                if new_qty <= 0:
                    self._do_close(pos["id"], now)
                    result = {"status": "closed", "pos_id": pos["id"], "symbol": symbol}
                else:
                    pos["qty"] = str(new_qty)
                    self.positions_repo.upsert(pos)
                    result = pos
                if self.trades_repo:
                    self.trades_repo.insert({"ts": now, "symbol": symbol, "price": str(price), "qty": str(abs(qty)), "action": "reduce"})
                if self.audit_repo:
                    self.audit_repo.append({"ts": now, "type": "order_reduce", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        else:
            if new_qty <= 0:
                self._do_close(pos["id"], now)
                result = {"status": "closed", "pos_id": pos["id"], "symbol": symbol}
            else:
                pos["qty"] = str(new_qty)
                self.positions_repo.upsert(pos)
                result = pos
            if self.trades_repo:
                self.trades_repo.insert({"ts": now, "symbol": symbol, "price": str(price), "qty": str(abs(qty)), "action": "reduce"})
            if self.audit_repo:
                self.audit_repo.append({"ts": now, "type": "order_reduce", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        return result

    def close(self, pos_id: str) -> Dict[str, Any]:
        now = _now_iso()
        if self.uow is not None:
            with self.uow:
                self._do_close(pos_id, now)
        else:
            self._do_close(pos_id, now)
        if self.audit_repo:
            self.audit_repo.append({"ts": now, "type": "position_close", "pos_id": pos_id})
        return {"status": "ok", "pos_id": pos_id}

    def _do_close(self, pos_id: str, now: str) -> None:
        try:
            self.positions_repo.close(pos_id)
        except Exception:
            pos = self.positions_repo.get_by_id(pos_id) or {"id": pos_id}
            pos.update({"status": "closed", "closed_at": now})
            self.positions_repo.upsert(pos)

    # Совместимость: оставляем снимок/метрики интерфейса
    def get_snapshot(self) -> Dict[str, Any]:
        return {"open_positions": _safe_open_list(self.positions_repo)}

    def get_pnl(self) -> Decimal:
        return Decimal("0")

    def get_exposure(self) -> Decimal:
        total = Decimal("0")
        for p in _safe_open_list(self.positions_repo):
            try:
                qty = Decimal(str(p.get("qty", "0")))
            except Exception:
                qty = Decimal("0")
            total += abs(qty)
        return total
