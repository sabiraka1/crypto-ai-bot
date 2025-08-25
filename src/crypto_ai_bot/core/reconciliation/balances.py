from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ...utils.logging import get_logger

_log = get_logger("reconcile.balances")

@dataclass
class BalancesReconciler:
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus

    async def run_once(self) -> None:
        """
        Базовая сверка балансов по котируемой валюте.
        Если есть расхождения с локальными записями — только лог/событие.
        """
        try:
            # локальное «ожидание» берем по сумме cost в аудите как приблизительный показатель (paper)
            cur = self.storage.conn.execute("""
                SELECT SUM(CASE WHEN json_extract(payload,'$.side')='buy'
                                THEN CAST(json_extract(payload,'$.quote_amount') AS REAL)
                                ELSE 0 END)
                FROM audit
                WHERE type='order_placed'
            """)
            expected_quote = Decimal(str(cur.fetchone()[0] or 0))

            bal = await self.broker.fetch_balance()
            quote_ccy = "USDT"
            actual_quote = Decimal(str(bal.get(quote_ccy, "0")))

            # допускаем большую «погрешность» для demo
            if (expected_quote - actual_quote).copy_abs() > Decimal("0.01"):
                _log.warning("balance_mismatch", extra={
                    "quote": quote_ccy, "expected": str(expected_quote), "actual": str(actual_quote)
                })
                self.storage.audit.log("reconcile.balance_mismatch", {
                    "quote": quote_ccy,
                    "expected": str(expected_quote),
                    "actual": str(actual_quote),
                })
                try:
                    await self.bus.publish(
                        "reconcile.balance.mismatch",
                        {"quote": quote_ccy, "expected": str(expected_quote), "actual": str(actual_quote)},
                        key="balances",
                    )
                except Exception:
                    pass
        except Exception as exc:
            _log.error("balances_reconcile_failed", extra={"error": str(exc)})
