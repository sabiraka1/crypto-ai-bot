from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    storage: Storage
    broker: IBroker
    symbol: str
    timeout_ms: int = 120_000

    # мягкий режим
    rechecks: int = 2
    recheck_delay_sec: float = 3.0
    max_impact_pct: Decimal = dec("0")  # 0 = выключено

    # опциональная шина событий — чтобы можно было алертить без доп. зависимостей
    bus: AsyncEventBus | None = None

    _last_beat_ms: int = 0
    _last_healthy_price: Decimal | None = None

    def beat(self) -> None:
        self._last_beat_ms = now_ms()

    async def _publish(self, topic: str, payload: dict) -> None:
        if not self.bus:
            return
        try:
            await self.bus.publish(topic, payload, key=payload.get("symbol"))
        except Exception:
            pass

    async def check_and_trigger(self) -> None:
        if self._last_beat_ms <= 0:
            return
        if (now_ms() - self._last_beat_ms) < self.timeout_ms:
            return

        # мягкая проверка: несколько повторных пингов
        for _ in range(max(0, int(self.rechecks))):
            await asyncio.sleep(max(0.0, float(self.recheck_delay_sec)))
            if (now_ms() - self._last_beat_ms) < self.timeout_ms:
                _log.info("dms_recovered_on_recheck", extra={"symbol": self.symbol})
                return

        # проверка «ценового воздействия»
        try:
            if self.max_impact_pct > 0:
                t = await self.broker.fetch_ticker(self.symbol)
                last = dec(str(t.last or 0))
                if self._last_healthy_price is None:
                    self._last_healthy_price = last
                    _log.warning("dms_no_baseline_price", extra={"symbol": self.symbol})
                    return
                drop = (self._last_healthy_price - last) / self._last_healthy_price if self._last_healthy_price > 0 else dec("0")
                if drop > self.max_impact_pct / dec("100"):
                    msg = {"symbol": self.symbol, "drop_pct": str(drop * 100), "ts_ms": now_ms()}
                    _log.warning("dms_skip_on_impact_limit", extra=msg)
                    inc("dms_skip_impact_total", symbol=self.symbol)
                    await self._publish("safety.dms.skipped", msg)
                    return
        except Exception as exc:
            _log.error("dms_impact_check_failed", extra={"error": str(exc)})

        # триггер: закрываем всю базу по рынку (long-only)
        try:
            pos = self.storage.positions.get_position(self.symbol)
            base = dec(str(pos.base_qty or 0))
            if base > 0:
                od = await self.broker.create_market_sell_base(
                    symbol=self.symbol, 
                    base_amount=base,
                    client_order_id=f"dms_{self.symbol}_{now_ms()}"
                )
                self.storage.trades.add_from_order(od)
                inc("dms_trigger_total", symbol=self.symbol)
                payload = {"symbol": self.symbol, "amount": str(base), "order_id": od.id, "ts_ms": now_ms()}
                _log.error("dms_triggered_sell_all", extra=payload)
                await self._publish("safety.dms.triggered", payload)
        except Exception as exc:
            _log.error("dms_trigger_failed", extra={"error": str(exc), "symbol": self.symbol})
            inc("dms_trigger_errors_total", symbol=self.symbol)

    # Методы для соответствия SafetySwitchPort протоколу
    async def start(self) -> None:
        """Запуск DMS - инициализируем первый beat."""
        self.beat()
        _log.info("dms_started", extra={"symbol": self.symbol})
    
    async def ping(self) -> None:
        """Пинг для сброса таймера DMS."""
        self.beat()
    
    async def stop(self) -> None:
        """Остановка DMS - сбрасываем состояние."""
        self._last_beat_ms = 0
        self._last_healthy_price = None
        _log.info("dms_stopped", extra={"symbol": self.symbol})