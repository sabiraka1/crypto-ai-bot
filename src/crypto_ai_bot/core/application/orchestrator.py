from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional, Dict, Set

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute, EvalInputs
from crypto_ai_bot.core.application.reconciliation.positions import reconcile_positions_batch
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe

_log = get_logger("application.orchestrator")


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
        from time import perf_counter
        q = dec(str(getattr(self.settings, "FIXED_AMOUNT", 0) or 0))
        t0 = perf_counter()
        await eval_and_execute(
            storage=self.storage,
            broker=self.broker,
            bus=self.bus,
            risk=self.risk,
            settings=self.settings,
            inputs=EvalInputs(symbol=self.symbol, quote_amount=q),
        )
        observe("loop.eval.ms", (perf_counter() - t0) * 1000.0)


class _ExitsLoop:
    def __init__(self, *, symbol: str, storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort, settings: Any) -> None:
        self.symbol = symbol

    async def tick(self) -> None:
        await asyncio.sleep(0)


class _ReconcileLoop:
    def __init__(self, *, symbols: List[str], storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort) -> None:
        self.symbols = symbols
        self.storage = storage
        self.broker = broker
        self.bus = bus

    async def tick(self) -> None:
        from time import perf_counter
        t0 = perf_counter()
        await reconcile_positions_batch(symbols=self.symbols, storage=self.storage, broker=self.broker, bus=self.bus)
        observe("loop.reconcile.ms", (perf_counter() - t0) * 1000.0)


class _WatchdogLoop:
    def __init__(self, *, symbol: str, storage: StoragePort, broker: BrokerPort,
                 bus: EventBusPort) -> None:
        self._hc = HealthChecker(storage=storage, broker=broker, bus=bus, symbol=symbol)

    async def tick(self) -> None:
        await self._hc.check()


class _SettlementLoop:
    """Подтверждение сделок: поллинг fetch_order по полученным order_id из события trade.completed."""
    def __init__(self, *, symbol: str, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
        self.symbol = symbol
        self.broker = broker
        self.bus = bus
        self.settings = settings
        self._pending: Set[str] = set()
        self._max_retries = int(getattr(settings, "SETTLEMENT_MAX_RETRIES", 10) or 10)
        self._retry_delay = float(getattr(settings, "SETTLEMENT_RETRY_DELAY_SEC", 2.0) or 2.0)
        # подписка на завершённые сделки (в момент размещения)
        bus.subscribe("trade.completed", self._on_trade_completed)

    async def _on_trade_completed(self, payload: Dict[str, Any]) -> None:
        if (payload or {}).get("symbol") != self.symbol:
            return
        oid = (payload or {}).get("order_id") or ""
        if oid:
            self._pending.add(oid)

    async def tick(self) -> None:
        if not self._pending:
            await asyncio.sleep(0)
            return
        # копия, чтобы можно было модифицировать set по ходу
        to_check = list(self._pending)
        for oid in to_check:
            settled = await self._poll_one(oid)
            if settled:
                self._pending.discard(oid)

    async def _poll_one(self, oid: str) -> bool:
        tries = 0
        while tries < self._max_retries:
            tries += 1
            try:
                od = await self.broker.fetch_order(symbol=self.symbol, broker_order_id=oid)
                status = str(od.get("status", "") or od.get("info", {}).get("status", "")).lower()
                if status in {"closed", "done", "filled", "finished"}:
                    inc("settlement.ok")
                    await self.bus.publish("trade.settled", {"symbol": self.symbol, "order_id": oid, "status": status})
                    return True
                if status in {"canceled", "cancelled", "rejected"}:
                    inc("settlement.rejected")
                    await self.bus.publish("trade.failed_settlement", {"symbol": self.symbol, "order_id": oid, "status": status})
                    return True
            except Exception as exc:
                # сетевые/временные — попробуем ещё
                await asyncio.sleep(self._retry_delay)
                continue
            await asyncio.sleep(self._retry_delay)
        # не смогли подтвердить
        inc("settlement.timeout")
        await self.bus.publish("trade.settlement_timeout", {"symbol": self.symbol, "order_id": oid})
        return True  # снимаем из очереди, чтобы не зависало


class _MaintenanceLoop:
    """GC идемпотенции и прочее обслуживание."""
    def __init__(self, *, storage: StoragePort, settings: Any) -> None:
        self.storage = storage
        self.settings = settings

    async def tick(self) -> None:
        try:
            idem = getattr(self.storage, "idempotency", None)
            idem_repo = idem() if callable(idem) else None
            if idem_repo is not None:
                ttl = int(getattr(self.settings, "IDEMPOTENCY_TTL_SEC", 60) or 60)
                idem_repo.prune_older_than(max(ttl * 4, 300))
        except Exception as exc:
            _log.warning("idem_prune_failed", extra={"error": str(exc)})


# ========== Оркестратор ==========
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
        settlement_loop = _SettlementLoop(symbol=self.symbol, broker=self.broker, bus=self.bus, settings=self.settings)
        maintenance_loop = _MaintenanceLoop(storage=self.storage, settings=self.settings)

        self._tasks = [
            asyncio.create_task(self._runner(eval_loop.tick, float(getattr(self.settings, "EVAL_INTERVAL_SEC", 3) or 3)), name="eval-loop"),
            asyncio.create_task(self._runner(exits_loop.tick, float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5) or 5)), name="exits-loop"),
            asyncio.create_task(self._runner(reconcile_loop.tick, float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 10) or 10)), name="reconcile-loop"),
            asyncio.create_task(self._runner(watchdog_loop.tick, float(getattr(self.settings, "WATCHDOG_INTERVAL_SEC", 3) or 3)), name="watchdog-loop"),
            asyncio.create_task(self._runner(settlement_loop.tick, float(getattr(self.settings, "SETTLEMENT_INTERVAL_SEC", 7) or 7)), name="settlement-loop"),
            asyncio.create_task(self._runner(maintenance_loop.tick, float(getattr(self.settings, "MAINTENANCE_INTERVAL_SEC", 600) or 600)), name="maintenance-loop"),
        )
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
