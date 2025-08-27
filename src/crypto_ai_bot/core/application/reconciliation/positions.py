from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any

from ..storage.facade import Storage
from ..brokers.base import IBroker
from ..brokers.symbols import parse_symbol
from ...utils.logging import get_logger
from ...utils.time import now_ms


class PositionsReconciler:
    """Сверка позиции: локальная позиция vs. биржевой баланс по базовой валюте (spot/long-only)."""

    def __init__(self, *, storage: Storage, broker: IBroker, symbol: str, auto_fix: bool = True,
                 tolerance: Decimal = Decimal("0.00000001")) -> None:
        self._storage = storage
        self._broker = broker
        self._symbol = symbol
        self._auto = bool(auto_fix)
        self._tol = tolerance
        self._log = get_logger("recon.positions")

    async def run_once(self) -> Dict[str, Any]:
        local = self._storage.positions.get_position(self._symbol)
        try:
            bal = await self._broker.fetch_balance(self._symbol)
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        diff = bal.free_base - local.base_qty
        within = abs(diff) <= self._tol

        result: Dict[str, Any] = {
            "symbol": self._symbol,
            "local_base": str(local.base_qty),
            "exchange_base": str(bal.free_base),
            "diff": str(diff),
            "within_tolerance": within,
            "actions": [],
        }

        if within or not self._auto:
            return result

        # Микро-расхождение — просто корректируем БД.
        if abs(diff) < Decimal("0.0001"):
            self._storage.positions.set_base_qty(self._symbol, bal.free_base)
            result["actions"].append({"type": "db_correction", "new_local_base": str(bal.free_base)})
            self._log.warning("position_autofixed_db", extra={"symbol": self._symbol, "new_local_base": str(bal.free_base)})
            return result

        # Крупная разница — отражаем через виртуальную сделку (для честного PnL/истории)
        tkr = await self._broker.fetch_ticker(self._symbol)
        if diff > 0:
            # На бирже БОЛЬШЕ — докупка
            virt = {
                "symbol": self._symbol,
                "side": "buy",
                "amount": diff,
                "price": tkr.last,
                "cost": diff * tkr.last,
                "ts_ms": now_ms(),
                "status": "reconciliation",
            }
            self._storage.trades.add_reconciliation_trade(virt)
            self._storage.positions.update_from_trade(virt)
            result["actions"].append({"type": "virtual_buy", "amount": str(diff), "price": str(tkr.last)})
        else:
            # На бирже МЕНЬШЕ — продажа
            amount = abs(diff)
            virt = {
                "symbol": self._symbol,
                "side": "sell",
                "amount": amount,
                "price": tkr.last,
                "cost": amount * tkr.last,
                "ts_ms": now_ms(),
                "status": "reconciliation",
            }
            self._storage.trades.add_reconciliation_trade(virt)
            self._storage.positions.update_from_trade(virt)
            result["actions"].append({"type": "virtual_sell", "amount": str(amount), "price": str(tkr.last)})

        self._log.warning("position_autofixed_trade", extra=result)
        return result
