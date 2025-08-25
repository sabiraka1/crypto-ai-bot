from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ...utils.logging import get_logger

_log = get_logger("reconcile.positions")

@dataclass
class PositionsReconciler:
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    symbol: str

    async def run_once(self) -> None:
        """
        Базовая сверка позиции: если расхождение между локальной базовой позицией и биржевой > epsilon,
        логируем и публикуем событие. Исправление не выполняем — только сигнализация.
        """
        try:
            local_base = self.storage.positions.get_base_qty(self.symbol) or Decimal("0")
            try:
                bal = await self.broker.fetch_balance()
                # берём по base-валюте
                base_ccy = self.symbol.split("/")[0]
                remote_base = Decimal(str(bal.get(base_ccy, "0")))
            except Exception as exc:
                _log.error("fetch_balance_failed", extra={"error": str(exc)})
                return

            diff = (local_base - remote_base).copy_abs()
            epsilon = Decimal("0.00000001")
            if diff > epsilon:
                _log.warning("position_mismatch", extra={
                    "symbol": self.symbol, "local": str(local_base), "remote": str(remote_base)
                })
                self.storage.audit.log("reconcile.position_mismatch", {
                    "symbol": self.symbol,
                    "local": str(local_base),
                    "remote": str(remote_base),
                })
                try:
                    await self.bus.publish(
                        "reconcile.position.mismatch",
                        {"symbol": self.symbol, "local": str(local_base), "remote": str(remote_base)},
                        key=self.symbol.replace("/", "-").lower(),
                    )
                except Exception:
                    pass
        except Exception as exc:
            _log.error("positions_reconcile_failed", extra={"error": str(exc)})
