from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional

from .use_cases.eval_and_execute import eval_and_execute          # ✅ внутри core
from .events.bus import AsyncEventBus                              # ✅ внутри core
from .risk.manager import RiskManager                              # ✅ внутри core
from .risk.protective_exits import ProtectiveExits                 # ✅ внутри core
from .monitoring.health_checker import HealthChecker               # ✅ внутри core
from .storage.facade import Storage                                # ✅ внутри core
from .brokers.base import IBroker                                  # ✅ внутри core
from .brokers.symbols import parse_symbol                          # ✅ внутри core
from ..utils.logging import get_logger                             # ✅ из sibling-пакета utils
from ..utils.metrics import timer                                   # ✅ таймеры латентности


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

    # опционально: форсить действие в eval-цикле: "buy"|"sell"|"hold"|None
    force_eval_action: Optional[str] = None

    _tasks: Dict[str, asyncio.Task] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _last_beat_ms: int = field(default=0, init=False)

    # --- lifecycle ---
    def start(self) -> None:
        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
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
                # общий тик — сколько занял целиком
                with timer("orchestrator_eval_tick_ms", {"symbol": self.symbol}, unit="ms"):
                    # отдельно измеряем сам use-case
                    with timer("eval_and_execute_ms", {"symbol": self.symbol}, unit="ms"):
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
                pos = self.storage.positions.get_position(self.symbol)
                if pos.base_qty and pos.base_qty > 0:
                    await self.exits.ensure(symbol=self.symbol)
            except Exception as exc:
                log.error("ensure_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.exits_interval_sec)

    async def _reconcile_loop(self) -> None:
        log = get_logger("orchestrator.reconcile")
        while not self._stopping:
            try:
                # зачистить старые idempotency keys старше TTL*10
                try:
                    prune = getattr(self.storage.idempotency, "prune_older_than", None)
                    if callable(prune):
                        prune(self.settings.IDEMPOTENCY_TTL_SEC * 10)
                except Exception:
                    pass
                # аудит 7 дней
                try:
                    prune_audit = getattr(self.storage.audit, "prune_older_than", None)
                    if callable(prune_audit):
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
                hb = parse_symbol(self.symbol).as_pair
                await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": hb}, key=hb)
                self._last_beat_ms = rep.ts_ms
            except Exception as exc:
                log.error("watchdog_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.watchdog_interval_sec)
