from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from ..use_cases.eval_and_execute import eval_and_execute
from ..events.bus import AsyncEventBus
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..monitoring.health_checker import HealthChecker
from ..storage.facade import Storage
from ..brokers.base import IBroker
from ..brokers.symbols import parse_symbol
from ..reconciliation.orders import OrdersReconciler
from ..reconciliation.positions import PositionsReconciler
from ..reconciliation.balances import BalancesReconciler
from ..safety.dead_mans_switch import DeadMansSwitch
from ...utils.logging import get_logger

# Метрики — безопасно
try:
    from ...utils.metrics import inc, timer  # type: ignore
except Exception:  # pragma: no cover
    def inc(*args, **kwargs):  # type: ignore
        return None
    from contextlib import contextmanager
    @contextmanager
    def timer(*args, **kwargs):  # type: ignore
        yield


@dataclass
class Orchestrator:
    symbol: str
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    settings: "Settings"

    eval_interval_sec: float = 1.0
    exits_interval_sec: float = 2.0
    reconcile_interval_sec: float = 5.0
    watchdog_interval_sec: float = 2.0

    force_eval_action: Optional[str] = None
    dms_timeout_ms: int = 120_000

    _tasks: Dict[str, asyncio.Task] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _last_beat_ms: int = field(default=0, init=False)

    _dms: Optional[DeadMansSwitch] = field(default=None, init=False)
    _recon_orders: Optional[OrdersReconciler] = field(default=None, init=False)
    _recon_pos: Optional[PositionsReconciler] = field(default=None, init=False)
    _recon_bal: Optional[BalancesReconciler] = field(default=None, init=False)

    # health/debug
    _started_at: float = field(default=0.0, init=False)
    _last_run: Dict[str, int] = field(default_factory=dict, init=False)          # loop -> ts_ms
    _last_duration: Dict[str, float] = field(default_factory=dict, init=False)   # loop -> ms
    _error_counts: Dict[str, int] = field(default_factory=dict, init=False)      # loop -> n

    def start(self) -> None:
        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._started_at = time.time()

        # safety/reconcile
        self._dms = DeadMansSwitch(self.storage, self.broker, self.symbol, timeout_ms=self.dms_timeout_ms)
        self._recon_orders = OrdersReconciler(self.broker, self.symbol)
        self._recon_pos = PositionsReconciler(storage=self.storage, broker=self.broker, symbol=self.symbol)
        self._recon_bal = BalancesReconciler(self.broker, self.symbol)

        self._tasks["eval"] = loop.create_task(self._eval_loop(), name="orc-eval")
        self._tasks["exits"] = loop.create_task(self._exits_loop(), name="orc-exits")
        self._tasks["reconcile"] = loop.create_task(self._reconcile_loop(), name="orc-reconcile")
        self._tasks["watchdog"] = loop.create_task(self._watchdog_loop(), name="orc-watchdog")

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stopping = True
        for t in list(self._tasks.values()):
            if not t.done():
                t.cancel()
        try:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        finally:
            self._tasks.clear()

    def status(self) -> dict:
        return {
            "running": bool(self._tasks),
            "tasks": {k: (not v.done()) for k, v in self._tasks.items()},
            "last_beat_ms": self._last_beat_ms,
        }

    def health_status(self) -> dict:
        """Расширенный статус для /status (диагностика циклов)."""
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return {
            "running": bool(self._tasks),
            "uptime_seconds": uptime,
            "loops": {
                name: {
                    "running": not task.done(),
                    "last_run_ms": self._last_run.get(name),
                    "last_duration_ms": self._last_duration.get(name),
                    "errors": self._error_counts.get(name, 0),
                }
                for name, task in self._tasks.items()
            },
        }

    # ---------- loops with backpressure ----------

    async def _loop_with_backpressure(self, name: str, interval: float, coro_factory: Callable[[], Awaitable[None]]) -> None:  # type: ignore[name-defined]
        # Приватный helper, чтобы не дублировать код
        while not self._stopping:
            t0 = time.perf_counter()
            try:
                with timer("orchestrator_cycle_ms", {"loop": name}):
                    await asyncio.wait_for(coro_factory(), timeout=interval * 0.9)
                inc("orchestrator_cycles_total", {"loop": name, "status": "success"})
            except asyncio.TimeoutError:
                inc("orchestrator_cycles_total", {"loop": name, "status": "timeout"})
                get_logger(f"orchestrator.{name}").warning("cycle_timeout", extra={"interval": interval})
            except Exception as exc:  # noqa: BLE001
                self._error_counts[name] = self._error_counts.get(name, 0) + 1
                inc("orchestrator_cycles_total", {"loop": name, "status": "error"})
                get_logger(f"orchestrator.{name}").error("cycle_failed", extra={"error": str(exc)})
            finally:
                elapsed = (time.perf_counter() - t0)
                self._last_run[name] = int(time.time() * 1000)
                self._last_duration[name] = round(elapsed * 1000.0, 3)
                sleep_time = max(0.0, interval - elapsed)
                await asyncio.sleep(sleep_time)

    async def _eval_loop(self) -> None:
        async def body() -> None:
            await eval_and_execute(
                symbol=self.symbol,
                storage=self.storage,
                broker=self.broker,
                bus=self.bus,
                exchange=self.settings.EXCHANGE,
                fixed_quote_amount=self.settings.FIXED_AMOUNT,
                idempotency_bucket_ms=self.settings.IDEMPOTENCY_BUCKET_MS,
                idempotency_ttl_sec=self.settings.IDEMPOTENCY_TTL_SEC,
                force_action=self.force_eval_action,
                risk_manager=self.risk,
                protective_exits=self.exits,
            )
            if self._dms:
                self._dms.beat()
        await self._loop_with_backpressure("eval", self.eval_interval_sec, body)

    async def _exits_loop(self) -> None:
        async def body() -> None:
            pos = self.storage.positions.get_position(self.symbol)
            if pos.base_qty and pos.base_qty > 0:
                await self.exits.ensure(symbol=self.symbol)
        await self._loop_with_backpressure("exits", self.exits_interval_sec, body)

    async def _reconcile_loop(self) -> None:
        async def body() -> None:
            # housekeeping
            try:
                prune = getattr(self.storage.idempotency, "prune_older_than", None)
                if callable(prune):
                    prune(self.settings.IDEMPOTENCY_TTL_SEC * 10)
            except Exception:
                pass
            try:
                prune_audit = getattr(self.storage.audit, "prune_older_than", None)
                if callable(prune_audit):
                    prune_audit(days=7)
            except Exception:
                pass

            if self._recon_orders:
                await self._recon_orders.run_once()
            if self._recon_pos:
                await self._recon_pos.run_once()
            if self._recon_bal:
                await self._recon_bal.run_once()
        await self._loop_with_backpressure("reconcile", self.reconcile_interval_sec, body)

    async def _watchdog_loop(self) -> None:
        async def body() -> None:
            rep = await self.health.check(symbol=self.symbol)
            hb = parse_symbol(self.symbol).base + "/" + parse_symbol(self.symbol).quote
            await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": hb}, key=hb)
            self._last_beat_ms = rep.ts_ms
            if self._dms:
                await self._dms.check_and_trigger()
        await self._loop_with_backpressure("watchdog", self.watchdog_interval_sec, body)
