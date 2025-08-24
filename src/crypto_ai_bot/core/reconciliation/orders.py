from __future__ import annotations

from dataclasses import dataclass

from ...utils.logging import get_logger
from ..storage.facade import Storage
from ..brokers.base import IBroker


@dataclass
class OrdersReconciler:
    """Пытается сопоставить локальные ордера/сделки с биржевыми."""
    storage: Storage
    broker: IBroker
    symbol: str

    def __post_init__(self) -> None:
        self._log = get_logger("reconcile.orders")

    async def run_once(self) -> None:
        # CCXT не всегда имеет fetch_open_orders в унифицированном виде для paper.
        # Делаем мягко: если у брокера есть метод — используем; иначе пропускаем.
        fetch = getattr(self.broker, "fetch_open_orders", None)
        if not callable(fetch):
            return
        try:
            _ = await fetch(self.symbol)  # список открытых ордеров на бирже
            # На данном этапе мы только прогреваем путь и проверяем наличие API.
            # Сопоставление с локальными записями будет добавлено позже.
        except Exception as exc:
            self._log.error("fetch_open_orders_failed", extra={"error": str(exc)})
