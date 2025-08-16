from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, List, Protocol

# uow protocol
try:
    from crypto_ai_bot.core.storage.interfaces import UnitOfWork as UnitOfWork  # type: ignore
except Exception:
    class UnitOfWork(Protocol):  # fallback
        def __enter__(self) -> Any: ...
        def __exit__(self, exc_type, exc, tb) -> None: ...


# --- интерфейсы репозиториев (узкая прослойка для типизации) ---
class PositionsRepo(Protocol):
    def upsert(self, position: Dict[str, Any]) -> None: ...
    def get_open(self) -> List[Dict[str, Any]]: ...
    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]: ...
    def close(self, pos_id: str) -> None: ...


class TradesRepo(Protocol):
    def insert(self, trade: Dict[str, Any]) -> None: ...


class AuditRepo(Protocol):
    def append(self, record: Dict[str, Any]) -> None: ...


# --- модульные (глобальные) зависимости, чтобы остальной код мог работать как раньше ---
_POS_REPO: Optional[PositionsRepo] = None
_TRD_REPO: Optional[TradesRepo] = None
_AUDIT_REPO: Optional[AuditRepo] = None
_UOW: Optional[UnitOfWork] = None


def configure_repositories(*, positions_repo: PositionsRepo, trades_repo: Optional[TradesRepo] = None, audit_repo: Optional[AuditRepo] = None) -> None:
    global _POS_REPO, _TRD_REPO, _AUDIT_REPO
    _POS_REPO = positions_repo
    _TRD_REPO = trades_repo
    _AUDIT_REPO = audit_repo


def configure_uow(uow: UnitOfWork) -> None:
    global _UOW
    _UOW = uow


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_open_by_symbol(repo: PositionsRepo, symbol: str) -> Optional[Dict[str, Any]]:
    for p in repo.get_open():
        if p.get("symbol") == symbol and p.get("status") == "open":
            return p
    return None


@dataclass
class PositionManager:
    """
    Класс-обёртка над репозиториями позиций/сделок.
    Совместим с тестами, ожидающими класс в crypto_ai_bot.core.positions.manager.
    """
    positions_repo: PositionsRepo
    trades_repo: Optional[TradesRepo] = None
    audit_repo: Optional[AuditRepo] = None
    uow: Optional[UnitOfWork] = None

    # --- операции ---
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
        Если есть открытая позиция по символу — увеличиваем qty, иначе открываем новую (side выводим из знака qty).
        Возвращает снапшот для тестов.
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
        return self.get_snapshot()

    def reduce(self, symbol: str, qty: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Снижаем позицию по символу на qty. Если qty >= текущего размера — закрываем.
        """
        now = _now_iso()
        pos = _find_open_by_symbol(self.positions_repo, symbol)
        if pos is None:
            # ничего не делаем, возвращаем снапшот
            return self.get_snapshot()

        cur_qty = Decimal(str(pos.get("qty", "0")))
        new_qty = cur_qty - abs(qty)
        if self.uow is not None:
            with self.uow:
                if new_qty <= 0:
                    self._do_close(pos["id"], now)
                else:
                    pos["qty"] = str(new_qty)
                    self.positions_repo.upsert(pos)
                if self.trades_repo:
                    self.trades_repo.insert({"ts": now, "symbol": symbol, "price": str(price), "qty": str(abs(qty)), "action": "reduce"})
                if self.audit_repo:
                    self.audit_repo.append({"ts": now, "type": "order_reduce", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        else:
            if new_qty <= 0:
                self._do_close(pos["id"], now)
            else:
                pos["qty"] = str(new_qty)
                self.positions_repo.upsert(pos)
            if self.trades_repo:
                self.trades_repo.insert({"ts": now, "symbol": symbol, "price": str(price), "qty": str(abs(qty)), "action": "reduce"})
            if self.audit_repo:
                self.audit_repo.append({"ts": now, "type": "order_reduce", "symbol": symbol, "qty": str(abs(qty)), "price": str(price)})
        return self.get_snapshot()

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

    # --- запросы состояния ---
    def get_snapshot(self) -> Dict[str, Any]:
        opens = self.positions_repo.get_open()
        return {"open_positions": opens}

    def get_pnl(self) -> Decimal:
        return Decimal("0")

    def get_exposure(self) -> Decimal:
        try:
            total = Decimal("0")
            for p in self.positions_repo.get_open():
                qty = Decimal(str(p.get("qty", "0")))
                total += abs(qty)
            return total
        except Exception:
            return Decimal("0")


# --- модульный API в стиле функций (совместимость со старым кодом) ---
def _require_repo() -> PositionsRepo:
    if _POS_REPO is None:
        raise RuntimeError("Positions repository is not configured. Call positions.manager.configure_repositories(...) first.")
    return _POS_REPO


def open(symbol: str, side: str, size: Decimal, *, sl: Optional[Decimal] = None, tp: Optional[Decimal] = None) -> Dict[str, Any]:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.open(symbol, side, size, sl=sl, tp=tp)


def partial_close(pos_id: str, size: Decimal) -> Dict[str, Any]:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.partial_close(pos_id, size)


def close(pos_id: str) -> Dict[str, Any]:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.close(pos_id)


def get_snapshot() -> Dict[str, Any]:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.get_snapshot()


def get_pnl() -> Decimal:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.get_pnl()


def get_exposure() -> Decimal:
    mgr = PositionManager(_require_repo(), _TRD_REPO, _AUDIT_REPO, _UOW)
    return mgr.get_exposure()
