from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ...utils.logging import get_logger


@dataclass
class DiscrepancyHandler:
    """Единая точка реакций на расхождения. Пока — лог/метрики, без автодействий."""
    def __post_init__(self) -> None:
        self._log = get_logger("reconcile")

    def orphaned_order(self, order_id: str) -> None:
        self._log.error("orphaned_order", extra={"order_id": order_id})

    def missing_order_on_exchange(self, order_id: str) -> None:
        self._log.error("missing_order_on_exchange", extra={"order_id": order_id})

    def balance_mismatch(self, currency: str, expected: Decimal, actual: Decimal) -> None:
        self._log.error(
            "balance_mismatch",
            extra={"currency": currency, "expected": str(expected), "actual": str(actual)},
        )
