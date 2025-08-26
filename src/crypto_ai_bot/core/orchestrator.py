from __future__ import annotations

import asyncio
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

# Метрики — делаем необязательными
try:
    from ...utils.metrics import inc, timer
except Exception:
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

    # --- lifecycle ---
    def start(self) -> None:
        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False

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
        return {"running": bool(self._tasks), "tasks": {k: (not v.done()) for k, v in self._tasks.items()}, "last_beat_ms": self._last_beat_ms}

    # --- helpers ---
    async def _run_tick(self, fn, *, interval: float, loop_name: str, timeout_ratio: float = 0.9) -> None:
        """Запуск тела цикла с контролем времени/таймаутом и ровным расписанием."""
        started = asyncio.get_event_loop().time()
        try:
            with timer("orchestrator_cycle_ms", {"loop": loop_name}):
                await asyncio.wait_for(fn(), timeout=max(0.1, interval * timeout_ratio))
            inc("orchestrator_cycles_total", {"loop": loop_name, "status": "success"})
        except asyncio.TimeoutError:
            get_logger(f"orchestrator.{loop_name}").error("loop_timeout", extra={"interval": interval})
            inc("orchestrator_cycles_total", {"loop": loop_name, "status": "timeout"})
        except Exception as exc:
            get_logger(f"orchestrator.{loop_name}").error("loop_failed", extra={"error": str(exc)})
            inc("orchestrator_cycles_total", {"loop": loop_name, "status": "error"})
        finally:
            elapsed = asyncio.get_event_loop().time() - started
            sleep_for = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_for)

    # --- loops ---
    async def _eval_loop(self) -> None:
        async def body():
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
        while not self._stopping:
            await self._run_tick(body, interval=self.eval_interval_sec, loop_name="eval")

    async def _exits_loop(self) -> None:
        async def body():
            pos = self.storage.positions.get_position(self.symbol)
            if pos.base_qty and pos.base_qty > 0:
                await self.exits.ensure(symbol=self.symbol)
        while not self._stopping:
            await self._run_tick(body, interval=self.exits_interval_sec, loop_name="exits")

    async def _reconcile_loop(self) -> None:
        async def body():
            # лёгкий house-keeping
            prune = getattr(self.storage.idempotency, "prune_older_than", None)
            if callable(prune):
                try:
                    prune(self.settings.IDEMPOTENCY_TTL_SEC * 10)
                except Exception:
                    pass
            prune_audit = getattr(self.storage.audit, "prune_older_than", None)
            if callable(prune_audit):
                try:
                    prune_audit(days=7)
                except Exception:
                    pass
            if self._recon_orders:
                await self._recon_orders.run_once()
            if self._recon_pos:
                await self._recon_pos.run_once()
            if self._recon_bal:
                await self._recon_bal.run_once()
        while not self._stopping:
            await self._run_tick(body, interval=self.reconcile_interval_sec, loop_name="reconcile")

    async def _watchdog_loop(self) -> None:
        async def body():
            rep = await self.health.check(symbol=self.symbol)
            hb = parse_symbol(self.symbol).base + "/" + parse_symbol(self.symbol).quote
            await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": hb}, key=hb)
            self._last_beat_ms = rep.ts_ms
            if self._dms:
                await self._dms.check_and_trigger()
        while not self._stopping:
            await self._run_tick(body, interval=self.watchdog_interval_sec, loop_name="watchdog")
