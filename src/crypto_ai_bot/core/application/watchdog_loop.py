from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Any

from crypto_ai_bot.core.application.ports import EventBusPort, SafetySwitchPort
from crypto_ai_bot.core.application.symbols import parse_symbol
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils import metrics as M
from crypto_ai_bot.utils.budget_guard import check as budget_check

_log = get_logger("loop.watchdog")


class WatchdogLoop:
    """
    Следит за здоровьем (health checker), метриками SLA и DMS.
    Вызывает переданные колбэки auto_pause/auto_resume.
    """

    def __init__(
        self,
        *,
        symbol: str,
        bus: EventBusPort,
        health_checker: Any,
        settings: Any,
        watchdog_interval_sec: float,
        dms: SafetySwitchPort | None,
        is_paused: Callable[[], bool],
        auto_pause: Callable[[str, dict], Awaitable[None]],
        auto_resume: Callable[[str, dict], Awaitable[None]],
        flight_cm: Callable[[], Awaitable],  # async context manager
    ) -> None:
        self.symbol = symbol
        self.bus = bus
        self.health = health_checker
        self.settings = settings
        self.interval = float(max(watchdog_interval_sec, 0.1))
        self.dms = dms
        self.is_paused = is_paused
        self.auto_pause = auto_pause
        self.auto_resume = auto_resume
        self.flight_cm = flight_cm
        self._stopping = False
        # пороги
        self.err_pause = float(getattr(self.settings, "AUTO_PAUSE_ERROR_RATE_5M", 0.50))
        self.err_resume = float(getattr(self.settings, "AUTO_RESUME_ERROR_RATE_5M", 0.20))
        self.lat_pause = float(getattr(self.settings, "AUTO_PAUSE_LATENCY_MS_5M", 2000.0))
        self.lat_resume = float(getattr(self.settings, "AUTO_RESUME_LATENCY_MS_5M", 1000.0))
        self.win = 5 * 60

    def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        while not self._stopping:
            try:
                async with self.flight_cm():
                    rep = await self.health.check(symbol=self.symbol)
                    hb = parse_symbol(self.symbol).base + "/" + parse_symbol(self.symbol).quote
                    await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": hb, "ts_ms": now_ms()}, key=hb)

                    if self.dms:
                        await self.dms.check_and_trigger()

                    labels = {}
                    er = M.error_rate(labels, self.win)
                    al = M.avg_latency_ms(labels, self.win)

                    if (er >= self.err_pause) or (al >= self.lat_pause):
                        await self.auto_pause("sla_threshold_exceeded",
                                              {"error_rate_5m": f"{er:.4f}", "avg_latency_ms_5m": f"{al:.2f}"})
                    elif self.is_paused() and (er <= self.err_resume) and (al <= self.lat_resume):
                        # проверим бюджет перед авто-возвратом
                        if budget_check(getattr(self.health, "storage", None) or getattr(self, "storage", None) or None, self.symbol, self.settings) is None:
                            await self.auto_resume("sla_stabilized_and_budget_ok",
                                                   {"error_rate_5m": f"{er:.4f}", "avg_latency_ms_5m": f"{al:.2f}"})
            except Exception as exc:
                _log.error("watchdog_loop_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.interval)
