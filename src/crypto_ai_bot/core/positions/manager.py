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
        now = datetime.now(timezone.utc).isoformat()
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

    def partial_close(self, pos_id: str, size: Decimal) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        if self.uow is not None:
            with self.uow:
                if self.trades_repo:
                    self.trades_repo.insert({"ts": now, "pos_id": pos_id, "qty": str(size), "context": {"action": "partial_close"}})
                if self.audit_repo:
                    self.audit_repo.append({"ts": now, "type": "position_partial_close", "pos_id": pos_id, "qty": str(size)})
        else:
            if self.trades_repo:
                self.trades_repo.insert({"ts": now, "pos_id": pos_id, "qty": str(size), "context": {"action": "partial_close"}})
            if self.audit_repo:
                self.audit_repo.append({"ts": now, "type": "position_partial_close", "pos_id": pos_id, "qty": str(size)})
        return {"status": "ok", "pos_id": pos_id, "closed_qty": str(size)}

    def close(self, pos_id: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
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
        # без цен/истории делаем заглушку
        return Decimal("0")

    def get_exposure(self) -> Decimal:
        # вычисляем экспозицию как сумму |qty|
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
