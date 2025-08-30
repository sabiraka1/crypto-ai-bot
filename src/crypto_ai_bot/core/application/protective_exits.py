from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort, OrderLike
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("protective_exits")


@dataclass
class ProtectiveExits:
    storage: StoragePort
    broker: BrokerPort
    bus: EventBusPort
    settings: Any

    async def ensure(self, *, symbol: str) -> None:
        """
        Поддерживающая логика: может выставлять защитные уровни (если появятся).
        Пока — no-op, чтобы не создавать скрытых зависимостей.
        """
        return None

    async def check_and_execute(self, *, symbol: str) -> Optional[OrderLike]:
        """
        Простой TP/SL long-only: при наличии позиции и настроек порогов.
        - TAKE_PROFIT_PCT / STOP_LOSS_PCT (число, проценты)
        """
        pos = self.storage.positions.get_position(symbol)
        base = dec(str(getattr(pos, "base_qty", 0) or 0))
        if base <= 0:
            return None

        entry = dec(str(getattr(pos, "avg_entry_price", 0) or 0))
        if entry <= 0:
            return None

        try:
            tp = dec(str(getattr(self.settings, "TAKE_PROFIT_PCT", "0") or "0"))
            sl = dec(str(getattr(self.settings, "STOP_LOSS_PCT", "0") or "0"))
        except Exception:
            tp = sl = dec("0")

        if tp <= 0 and sl <= 0:
            return None

        # Текущая рыночная цена
        t = await self.broker.fetch_ticker(symbol)
        last = dec(str(getattr(t, "last", 0) or 0))
        if last <= 0:
            return None

        should_exit = False
        reason = ""

        if tp > 0:
            target = entry * (dec("1") + tp / dec("100"))
            if last >= target:
                should_exit = True
                reason = f"take_profit_{tp}%"

        if (not should_exit) and sl > 0:
            floor = entry * (dec("1") - sl / dec("100"))
            if last <= floor:
                should_exit = True
                reason = f"stop_loss_{sl}%"

        if not should_exit:
            return None

        coid = f"exit:{symbol}:{int(now_ms() // 1000)}"
        try:
            od = await self.broker.create_market_sell_base(symbol=symbol, base_amount=base, client_order_id=coid)
            await self.bus.publish("exit.executed", {
                "symbol": symbol, "reason": reason, "amount": str(base),
                "price": str(od.price or ""), "client_order_id": od.client_order_id, "ts_ms": now_ms()
            }, key=symbol)
            return od
        except Exception as exc:
            _log.error("exit_execute_failed", extra={"symbol": symbol, "error": str(exc)})
            return None
