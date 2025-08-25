from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
from decimal import Decimal

from ..brokers.base import IBroker, OrderDTO
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ...utils.logging import get_logger

_log = get_logger("reconcile.orders")

@dataclass
class OrdersReconciler:
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    symbol: str

    async def run_once(self) -> None:
        """
        Простейшая сверка «зависших» ордеров: если локально есть ордера в статусе open,
        а на бирже они отсутствуют или закрыты — публикуем событие и фиксируем в аудите.
        Реализация намеренно лёгкая: ccxt-адаптеров пока не трогаем.
        """
        try:
            # Локальная выборка (если есть репозиторий ордеров — используй его;
            # иначе опираемся на аудит как на источник фактов)
            open_local: List[str] = []
            try:
                # попробуем вытащить ID ордеров из аудита
                cur = self.storage.conn.execute("""
                    SELECT DISTINCT json_extract(payload, '$.order_id')
                    FROM audit
                    WHERE type='order_placed' AND json_extract(payload,'$.status')='open'
                """)
                open_local = [r[0] for r in cur.fetchall() if r[0]]
            except Exception:
                open_local = []

            if not open_local:
                return

            # На бирже актуальные ордера
            try:
                open_remote = await self.broker.fetch_open_orders(self.symbol)
                remote_ids = {o.id for o in open_remote if o and o.id}
            except Exception as exc:
                _log.error("fetch_open_orders_failed", extra={"error": str(exc)})
                return

            for oid in open_local:
                if oid not in remote_ids:
                    # локально «open», на бирже — нет → сигналим и пишем в аудит
                    _log.warning("orphaned_local_order", extra={"order_id": oid, "symbol": self.symbol})
                    self.storage.audit.log("reconcile.orphaned_local_order", {
                        "symbol": self.symbol,
                        "order_id": oid,
                    })
                    try:
                        await self.bus.publish(
                            "reconcile.order.orphaned_local",
                            {"symbol": self.symbol, "order_id": oid},
                            key=self.symbol.replace("/", "-").lower(),
                        )
                    except Exception:
                        pass
        except Exception as exc:
            _log.error("orders_reconcile_failed", extra={"error": str(exc)})
