from __future__ import annotations

from typing import Optional, Any
from ..brokers.base import IBroker
from ..storage.facade import Storage
from ..risk.protective_exits import ProtectiveExits
from ...utils.logging import get_logger

class OrdersReconciler:
    """
    Мягкая сверка открытых ордеров.
    Ничего не изменяет в БД/на бирже — только логирует несоответствия.
    Безопасно работает даже если брокер не поддерживает fetch_open_orders.
    """

    def __init__(self, *, storage: Storage, broker: IBroker, symbol: str) -> None:
        self._log = get_logger("reconcile.orders")
        self._storage = storage
        self._broker = broker
        self._symbol = symbol

    async def run_once(self) -> None:
        # безопасно проверим наличие метода у брокера
        fetch_open = getattr(self._broker, "fetch_open_orders", None)
        if not callable(fetch_open):
            self._log.info("skip_no_fetch_open_orders")
            return

        try:
            open_orders = await fetch_open(self._symbol)  # type: ignore
        except Exception as exc:
            self._log.error("fetch_open_orders_failed", extra={"error": str(exc)})
            return

        # локально у нас пока нет репозитория ордеров — сверяемся на уровне факта “есть/нет открытых”
        if not open_orders:
            self._log.info("ok_no_open_orders")
            return

        # если есть открытые ордера — просто залогируем их id/side/amount
        for o in open_orders:
            try:
                oid = getattr(o, "id", None) or (isinstance(o, dict) and o.get("id"))
                side = getattr(o, "side", None) or (isinstance(o, dict) and o.get("side"))
                amount = getattr(o, "amount", None) or (isinstance(o, dict) and o.get("amount"))
                self._log.warning("open_order_exists", extra={"id": oid, "side": side, "amount": str(amount)})
            except Exception:
                self._log.warning("open_order_unknown_format")
