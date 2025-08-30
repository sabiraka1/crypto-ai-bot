from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Optional

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute, EvalInputs
from crypto_ai_bot.core.application.reconciliation.positions import reconcile_positions_batch
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe

_log = get_logger("application.orchestrator")


# ========== МАЛЫЕ КЛАССЫ ЦИКЛОВ (внутри файла, без новых пакетов) ==========

class _EvalLoop:
    def __init__(self, *, symbol: str, storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort, risk: RiskManager, settings: Any) -> None:
        self.symbol = symbol
        self.storage = storage
        self.broker = broker
        self.bus = bus
        self.risk = risk
        self.settings = settings

    async def tick(self) -> None:
        q = dec(str(getattr(self.settings, "FIXED_AMOUNT", 0) or 0))
        t0 = asyncio.get_event_loop().time()
        res = await eval_and_execute(
            storage=self.storage,
            broker=self.broker,
            bus=self.bus,
            risk=self.risk,
            settings=self.settings,
            inputs=EvalInputs(symbol=self.symbol, quote_amount=q),
        )
        observe("loop.eval.ms", (asyncio.get_event_loop().time() - t0) * 1000.0)
        if res.ok:
            inc("loop.eval.ok", {"symbol": self.symbol})


class _ExitsLoop:
    """Заглушка под защитные выходы/стопы; оставляем лёгкий каркас."""
    def __init__(self, *, symbol: str, storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort, settings: Any) -> None:
        self.symbol = symbol
        self.storage = storage
        self.broker = broker
        self.bus = bus
        self.settings = settings

    async def tick(self) -> None:
        # здесь может быть trailing stop / hard stop в будущем
        await asyncio.sleep(0)  # no-op


class _ReconcileLoop:
    def __init__(self, *, symbols: List[str], storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort) -> None:
        self.symbols = symbols
        self.storage = storage
        self.broker = broker
        self.bus = bus

    async def tick(self) -> None:
        t0 = asyncio.get_event_loop().time()
        await reconcile_positions_batch(
            symbols=self.symbols,
            storage=self.storage,
            broker=self.broker,
            bus=self.bus,
        )
        observe("loop.reconcile.ms", (asyncio.get_event_loop().time() - t0) * 1000.0)


class _WatchdogLoop:
    def __init__(self, *, symbol: str, storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort) -> None:
        self._hc = HealthChecker(storage=storage, broker=broker, bus=bus, symbol=symbol)

    async def tick(self) -> None:
        await self._hc.check()


# ========== ОРКЕСТРАТОР (тонкий координатор) ==========

@dataclass
class Orchestrator:
    symbol: str
    storage: StoragePort
    broker: BrokerPort
    bus: EventBusPort
    risk: RiskManager
    settings: Any

    _running: bool = False
    _paused: bool = False
    _tasks: List[asyncio.Task] = None

    def __post_init__(self) -> None:
        self._tasks = []

    # ---- управление ----
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._paused = False
        inc("orchestrator.start", {"symbol": self.symbol})

        eval_loop = _EvalLoop(symbol=self.symbol, storage=self.storage, broker=self.broker, bus=self.bus, risk=self.risk, settings=self.settings)
        exits_loop = _ExitsLoop(symbol=self.symbol, storage=self.storage, broker=self.broker, bus=self.bus, settings=self.settings)
        reconcile_loop = _ReconcileLoop(symbols=[self.symbol], storage=self.storage, broker=self.broker, bus=self.bus)
        watchdog_loop = _WatchdogLoop(symbol=self.symbol, storage=self.storage, broker=self.broker, bus=self.bus)

        self._tasks = [
            asyncio.create_task(self._runner(eval_loop.tick, float(getattr(self.settings, "EVAL_INTERVAL_SEC", 3) or 3)), name="eval-loop"),
            asyncio.create_task(self._runner(exits_loop.tick, float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5) or 5)), name="exits-loop"),
            asyncio.create_task(self._runner(reconcile_loop.tick, float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 10) or 10)), name="reconcile-loop"),
            asyncio.create_task(self._runner(watchdog_loop.tick, float(getattr(self.settings, "WATCHDOG_INTERVAL_SEC", 3) or 3)), name="watchdog-loop"),
        ]
        _log.info("orchestrator_started", extra={"symbol": self.symbol})

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._paused = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _log.error("task_cancel_error", extra={"task": t.get_name(), "error": str(exc)})
        self._tasks.clear()
        inc("orchestrator.stop", {"symbol": self.symbol})
        _log.info("orchestrator_stopped", extra={"symbol": self.symbol})

    async def pause(self) -> None:
        self._paused = True
        inc("orchestrator.pause", {"symbol": self.symbol})
        _log.info("orchestrator_paused", extra={"symbol": self.symbol})

    async def resume(self) -> None:
        self._paused = False
        inc("orchestrator.resume", {"symbol": self.symbol})
        _log.info("orchestrator_resumed", extra={"symbol": self.symbol})

    def status(self) -> dict:
        return {
            "symbol": self.symbol,
            "running": self._running,
            "paused": self._paused,
            "tasks": [t.get_name() for t in self._tasks if not t.done()],
        }

    # ---- внутренний исполнитель цикла ----
    async def _runner(self, tick_coro, every_sec: float) -> None:
        while self._running:
            if not self._paused:
                try:
                    await tick_coro()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    _log.error("loop_error", extra={"error": str(exc)})
            await asyncio.sleep(every_sec)
