from __future__ import annotations

from decimal import Decimal
from typing import Optional
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ..storage.facade import Storage
from ..brokers.base import IBroker

class DeadMansSwitch:
    """
    Простой DMS: если нет heartbeat дольше timeout_ms — попытаться закрыть позицию по рынку.
    В paper-режиме безопасно; в live требует аккуратности.
    """

    def __init__(self, *, storage: Storage, broker: IBroker, timeout_ms: int = 120_000) -> None:
        self._log = get_logger("safety.dms")
        self._storage = storage
        self._broker = broker
        self._timeout_ms = timeout_ms
        self._last_beat_ms = now_ms()

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def check_and_trigger(self, *, symbol: str) -> None:
        if now_ms() - self._last_beat_ms <= self._timeout_ms:
            return
        try:
            pos = self._storage.positions.get_position(symbol)
            base = Decimal(str(pos.base_qty or "0"))
            if base > 0:
                close = getattr(self._broker, "create_market_sell_base", None)
                if callable(close):
                    await close(symbol=symbol, amount_base=base)
                    self._log.warning("dms_close_position", extra={"symbol": symbol, "amount_base": str(base)})
                else:
                    self._log.warning("dms_no_close_method", extra={"symbol": symbol})
            else:
                self._log.info("dms_no_position", extra={"symbol": symbol})
        except Exception as exc:
            self._log.error("dms_failed", extra={"error": str(exc)})
        finally:
            # чтобы не повторять закрытие каждую итерацию
            self._last_beat_ms = now_ms()
