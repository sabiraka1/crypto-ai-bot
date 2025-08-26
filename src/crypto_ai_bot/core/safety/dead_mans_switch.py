from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, Any

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ..brokers.symbols import parse_symbol
from ...utils.time import now_ms
from ...utils.logging import get_logger

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    """Простой DMS для spot long‑only.

    Поведение:
      • `beat()` — обновляет отметку «жив».
      • `check_and_trigger()` — если тишина > timeout_ms, ОДИН РАЗ продаёт всю базовую позицию по рынку.
      • Безопасен к повторным вызовам: после срабатывания больше не торгует.
    """

    storage: Storage
    broker: IBroker
    symbol: str
    timeout_ms: int = 120_000

    _last_beat_ms: Optional[int] = field(default=None, init=False)
    _triggered: bool = field(default=False, init=False)

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    def status(self) -> Dict[str, Any]:
        age = None
        if self._last_beat_ms is not None:
            age = max(0, now_ms() - self._last_beat_ms)
        return {
            "last_beat_ms": self._last_beat_ms,
            "age_ms": age,
            "timeout_ms": self.timeout_ms,
            "triggered": self._triggered,
            "symbol": self.symbol,
        }

    async def check_and_trigger(self) -> Optional[Dict[str, Any]]:
        if self._triggered:
            return None
        if self._last_beat_ms is None:
            # ещё не было пульса — не триггерим DMS, просто ждём первый beat()
            return None
        age = now_ms() - self._last_beat_ms
        if age < self.timeout_ms:
            return None

        # ——— ТРИГГЕР: продаём остаток base по рынку ———
        self._triggered = True  # идемпотентность на уровне процесса
        try:
            pos = self.storage.positions.get_position(self.symbol)
            base_qty: Decimal = pos.base_qty or Decimal("0")
        except Exception as exc:
            _log.error("dms_read_position_failed", extra={"error": str(exc)})
            base_qty = Decimal("0")

        if base_qty <= 0:
            _log.error("dms_trigger_no_position", extra={"symbol": self.symbol, "age_ms": age})
            return {
                "triggered": True,
                "sold": False,
                "reason": "no_base",
                "age_ms": age,
                "symbol": self.symbol,
            }

        # формируем client_order_id детерминированно по «бокету» времени
        bucket = (now_ms() // 1000) * 1000
        client_id = f"dms-{self.symbol.replace('/', '-')}-{bucket}"

        try:
            order = await self.broker.create_market_sell_base(
                symbol=self.symbol,
                base_amount=base_qty,
                client_order_id=client_id,
            )
            _log.error(
                "dms_forced_liquidation",
                extra={
                    "symbol": self.symbol,
                    "base_sold": str(base_qty),
                    "order_id": getattr(order, "id", None),
                },
            )
            return {
                "triggered": True,
                "sold": True,
                "base_sold": str(base_qty),
                "order_id": getattr(order, "id", None),
                "client_order_id": client_id,
                "age_ms": age,
                "symbol": self.symbol,
            }
        except Exception as exc:
            _log.error(
                "dms_liquidation_failed",
                extra={"symbol": self.symbol, "base": str(base_qty), "error": str(exc)},
            )
            return {
                "triggered": True,
                "sold": False,
                "reason": "broker_error",
                "error": str(exc),
                "age_ms": age,
                "symbol": self.symbol,
            }