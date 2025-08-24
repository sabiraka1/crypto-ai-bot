from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, List

from ..use_cases.eval_and_execute import eval_and_execute
from ..events.bus import AsyncEventBus
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..monitoring.health_checker import HealthChecker
from ..storage.facade import Storage
from ..brokers.base import IBroker
from ...utils.logging import get_logger

# новые импортируем мягко
try:
    from .reconciliation.orders import OrdersReconciler
    from .reconciliation.positions import PositionsReconciler
    from .reconciliation.balances import BalancesReconciler
except Exception:
    OrdersReconciler = PositionsReconciler = BalancesReconciler = None  # type: ignore

try:
    from .safety.dead_mans_switch import DeadMansSwitch
except Exception:
    DeadMansSwitch = None  # type: ignore


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

    _tasks: Dict[str, asyncio.Task] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _last_beat_ms: int = field(default=0, init=False)

    # внутренние
    _reconcilers: List[object] = field(default_factory=list, init=False)
    _dms: Optional[DeadMansSwitch] = field(default=None, init=False)

    # --- lifecycle ---
    def start(self) -> None:
        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False

        # ленивое создание DMS
        if DeadMansSwitch and self._dms is None:
            try:
                self._dms = DeadMansSwitch(
                    broker=self.broker,
                    storage=self.storage,
                    bus=self.bus,
                    symbol=self.symbol,
                    exchange=self.settings.EXCHANGE,
                )
            except Exception:
                self._dms = None

        # ленивое создание reconciler'ов
        if not self._reconcilers and OrdersReconciler and PositionsReconciler and BalancesReconciler:
            try:
                self._reconcilers = [
                    OrdersReconciler(self.storage, self.broker, self.symbol),
                    PositionsReconciler(self.storage, self.symbol),
                    BalancesReconciler(self.storage, self.broker, self.symbol),
                ]
            except Exception:
                self._reconcilers = []

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

    # --- loops ---
    async def _eval_loop(self) -> None:
        log = get_logger("orchestrator.eval")
        while not self._stopping:
            try:
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
            except Exception as exc:
                log.error("tick_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.eval_interval_sec)

    async def _exits_loop(self) -> None:
        log = get_logger("orchestrator.exits")
        while not self._stopping:
            try:
                pos = getattr(self.storage.positions, "get_position", None)
                if callable(pos):
                    p = pos(self.symbol)
                    base_qty = 0
                    if p is not None:
                        base_qty = getattr(p, "base_qty", getattr(p, "qty", 0))
                    if base_qty and base_qty > 0:
                        await self.exits.ensure(symbol=self.symbol)
            except Exception as exc:
                log.error("ensure_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.exits_interval_sec)

    async def _reconcile_loop(self) -> None:
        log = get_logger("orchestrator.reconcile")
        while not self._stopping:
            try:
                for r in self._reconcilers:
                    try:
                        rep = await r.reconcile()  # type: ignore
                        if not rep.ok:
                            # можно писать в reconciliation_log через storage.conn при желании
                            pass
                    except Exception as exc:
                        log.error("reconciler_failed", extra={"cls": r.__class__.__name__, "error": str(exc)})

                # мягкая чистка репозиториев, если методы есть
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

            except Exception as exc:
                log.error("reconcile_failed", extra={"error": str(exc)})

            await asyncio.sleep(self.reconcile_interval_sec)

    async def _watchdog_loop(self) -> None:
        log = get_logger("orchestrator.watchdog")
        while not self._stopping:
            try:
                rep = await self.health.check(symbol=self.symbol)
                # heartbeat DMS
                if self._dms:
                    self._dms.heartbeat()
                    await self._dms.check_and_trigger()

                # пульс в bus
                await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": self.symbol}, key=self.symbol)
                self._last_beat_ms = rep.ts_ms
            except Exception as exc:
                log.error("watchdog_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.watchdog_interval_sec)
