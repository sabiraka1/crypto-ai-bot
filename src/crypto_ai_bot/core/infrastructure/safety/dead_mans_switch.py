from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..storage.facade import Storage
from ..brokers.base import IBroker
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    storage: Storage
    broker: IBroker
    symbol: str
    timeout_ms: int = 120_000
    action: str = "close"  # "close" | "alert" | "both"

    _last_beat_ms: int = 0
    _triggered: bool = False

    def __post_init__(self) -> None:
        self._last_beat_ms = now_ms()

    def beat(self) -> None:
        """Регулярный heartbeat из оркестратора."""
        self._last_beat_ms = now_ms()
        self._triggered = False

    async def check_and_trigger(self) -> bool:
        """Проверяет таймаут и выполняет действие. Возвращает True, если срабатывание было."""
        if self._triggered:
            return False
        now = now_ms()
        elapsed = now - self._last_beat_ms
        if elapsed <= self.timeout_ms:
            return False

        _log.critical("dead_mans_switch_triggered", extra={"symbol": self.symbol, "timeout_ms": self.timeout_ms, "elapsed_ms": elapsed})
        self._triggered = True

        if self.action in ("close", "both"):
            await self._emergency_close()

        if self.action in ("alert", "both"):
            await self._send_alerts()

        return True

    async def _emergency_close(self) -> None:
        """Экстренное закрытие всех базовых единиц по символу."""
        try:
            pos = self.storage.positions.get_position(self.symbol)
            base_qty: Decimal = pos.base_qty or Decimal("0")
            if base_qty <= 0:
                _log.info("dms_no_position_to_close", extra={"symbol": self.symbol})
                return

            order = await self.broker.create_market_sell_base(
                symbol=self.symbol,
                base_amount=base_qty,
                client_order_id=f"dms-emergency-{now_ms()}",
            )
            _log.critical("dms_position_closed", extra={"symbol": self.symbol, "amount": str(base_qty), "order_id": order.id})
            try:
                self.storage.audit.log(
                    action="dms_emergency_close",
                    payload={"symbol": self.symbol, "amount": str(base_qty), "order_id": order.id, "reason": "heartbeat_timeout"},
                )
            except Exception:
                pass
        except Exception as exc:
            _log.error("dms_close_failed", extra={"error": str(exc)})

    async def _send_alerts(self) -> None:
        """Место для интеграции Telegram/Email и т.п."""
        try:
            self.storage.audit.log(action="dms_alert", payload={"symbol": self.symbol, "ts_ms": now_ms()})
        except Exception:
            pass
