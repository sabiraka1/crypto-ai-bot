from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any

from ..brokers.base import IBroker
from ...utils.logging import get_logger


class BalancesReconciler:
    """Простая сверка балансов (диагностика): возвращаем срез по USDT/BTC и общее количество активов."""

    def __init__(self, broker: IBroker) -> None:
        self._broker = broker
        self._log = get_logger("recon.balances")

    async def run_once(self) -> Dict[str, Any]:
        try:
            b = await self._broker.fetch_balance()
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

        # компактный срез, чтобы не тащить всё в логи
        usdt = Decimal(str(b.get("USDT", 0)))
        btc = Decimal(str(b.get("BTC", 0)))
        return {"assets_count": len(b), "USDT": str(usdt), "BTC": str(btc)}
