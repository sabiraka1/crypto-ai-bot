from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, OrderLike
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.partial_fills")

@dataclass
class PartialFillHandler:
    bus: EventBusPort

    async def handle(self, order: OrderLike, broker: BrokerPort) -> OrderLike | None:
        """
        Если частично исполнилось меньше порогового процента — добиваем остаток по рынку (long-only).
        Порог берём консервативный 95% от объёма исходного ордера.
        """
        try:
            filled = dec(str(order.filled or 0))
            amount = dec(str(order.amount or 0))
            if amount <= 0:
                return None
            ratio = (filled / amount) if amount > 0 else dec("1")
            if ratio >= dec("0.95"):
                return None

            remaining = amount - filled
            if order.side.lower() == "buy":
                # у buy amount — это quote? в нашей модели для buy это quote-amount,
                # а для sell — base-amount. Сохраняем ту же семантику.
                follow = await broker.create_market_buy_quote(symbol=self._symbol_from(order),
                                                              quote_amount=remaining,
                                                              client_order_id=f"{order.client_order_id}-pf")
            else:
                follow = await broker.create_market_sell_base(symbol=self._symbol_from(order),
                                                              base_amount=remaining,
                                                              client_order_id=f"{order.client_order_id}-pf")
            await self.bus.publish("trade.partial_followup", {
                "parent_client_order_id": order.client_order_id,
                "follow_client_order_id": follow.client_order_id,
            }, key=self._symbol_from(order))
            inc("partial_followup_total", symbol=self._symbol_from(order), side=order.side)
            return follow
        except Exception as exc:
            _log.error("partial_followup_failed", extra={"error": str(exc)})
            inc("partial_followup_errors_total")
            return None

    def _symbol_from(self, order: OrderLike) -> str:
        # В большинстве реализаций OrderDTO хранит символ; если нет — публиковать без ключа.
        return getattr(order, "symbol", "") or ""


# Функция-обертка для совместимости с orchestrator
async def settle_orders(symbol: str, storage: Any, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
    """
    Функция-обертка для проверки и обработки частично исполненных ордеров.
    В текущей версии - заглушка, так как нужна логика получения открытых ордеров.
    """
    # TODO: Реализовать когда будет хранилище открытых ордеров
    # 1. Получить список открытых ордеров из storage для symbol
    # 2. Проверить их статус через broker.fetch_order()
    # 3. Для частично исполненных создать PartialFillHandler и вызвать handle()
    _log.debug("settle_orders_check", extra={"symbol": symbol})