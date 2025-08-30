from __future__ import annotations

import asyncio, os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional, TYPE_CHECKING, Awaitable

from crypto_ai_bot.core.application.ports import (
    EventBusPort, StoragePort, BrokerPort, SafetySwitchPort
)
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.application.reconciliation.balances import BalancesReconciler
from crypto_ai_bot.core.application.symbols import parse_symbol
from crypto_ai_bot.core.application.eval_loop import EvalLoop
from crypto_ai_bot.core.application.exits_loop import ExitsLoop
from crypto_ai_bot.core.application.watchdog_loop import WatchdogLoop
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.budget_guard import check as budget_check

if TYPE_CHECKING:
    from crypto_ai_bot.core.infrastructure.settings import Settings  # только для типов

_log = get_logger("orchestrator")


def _fixed_amount_for(settings: "Settings", symbol: str) -> Decimal:
    p = parse_symbol(symbol)
    key = f"AMOUNT_{p.base}_{p.quote}".upper().replace("-", "_")
    raw = os.getenv(key) or getattr(settings, key, None)
    if raw is None or str(raw).strip() == "":
        return dec(str(getattr(settings, "FIXED_AMOUNT", "0")))
    try:
        return dec(str(raw))
    except Exception:
        return dec(str(getattr(settings, "FIXED_AMOUNT", "0")))


@dataclass
class Orchestrator:
    symbol: str
    storage: StoragePort
    broker: BrokerPort
    bus: EventBusPort
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    settings: "Settings"
    dms: Optional[SafetySwitchPort] = None

    eval_interval_sec: float = 60.0
    exits_interval_sec: float = 5.0
    reconcile_interval_sec: float = 60.0
    watchdog_interval_sec: float = 15.0

    force_eval_action: Optional[str] = None

    _tasks: Dict[str, asyncio.Task] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _last_beat_ms: int = field(default=0, init=False)
    _paused: bool = field(default=False, init=False)
    _auto_hold: bool = field(default=False, init=False)

    _recon_orders: Optional[OrdersReconciler] = field(default=None, init=False)
    _recon_bal: Optional[BalancesReconciler] = field(default=None, init=False)

    _inflight: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(0), init=False)
    _starting: bool = field(default=False, init=False)

    # ---------- public control ----------
    def start(self) -> None:
        if self._starting or self._tasks:
            return
        self._starting = True
        try:
            loop = asyncio.get_running_loop()
            self._stopping = False

            def _safe_float(v, default):
                try:
                    x = float(v)
                    return x if x > 0 else default
                except Exception:
                    return default

            self.eval_interval_sec = _safe_float(getattr(self.settings, "EVAL_INTERVAL_SEC", self.eval_interval_sec), self.eval_interval_sec)
            self.exits_interval_sec = _safe_float(getattr(self.settings, "EXITS_INTERVAL_SEC", self.exits_interval_sec), self.exits_interval_sec)
            self.reconcile_interval_sec = _safe_float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", self.reconcile_interval_sec), self.reconcile_interval_sec)
            self.watchdog_interval_sec = _safe_float(getattr(self.settings, "WATCHDOG_INTERVAL_SEC", self.watchdog_interval_sec), self.watchdog_interval_sec)

            try:
                self.risk.attach_storage(self.storage)
                self.risk.attach_settings(self.settings)
            except Exception:
                pass

            self._recon_orders = OrdersReconciler(self.broker, self.symbol)
            self._recon_bal = BalancesReconciler(self.broker, self.symbol)

            # loop instances
            self._eval_loop = EvalLoop(
                symbol=self.symbol,
                storage=self.storage,
                broker=self.broker,
                bus=self.bus,
                settings=self.settings,
                risk_manager=self.risk,
                protective_exits=self.exits,
                eval_interval_sec=self.eval_interval_sec,
                dms=self.dms,
                force_eval_action=self.force_eval_action,
                fee_estimate_pct=self.settings.FEE_PCT_ESTIMATE,
                is_paused=self.is_paused,
                fixed_amount_resolver=lambda s: _fixed_amount_for(self.settings, s),
                flight_cm=self._flight_cm,
                on_budget_exceeded=self._on_budget_exceeded,
            )
            self._exits_loop = ExitsLoop(
                symbol=self.symbol,
                storage=self.storage,
                protective_exits=self.exits,
                exits_interval_sec=self.exits_interval_sec,
                is_paused=self.is_paused,
                flight_cm=self._flight_cm,
            )
            self._watchdog_loop = WatchdogLoop(
                symbol=self.symbol,
                bus=self.bus,
                health_checker=self.health,
                settings=self.settings,
                watchdog_interval_sec=self.watchdog_interval_sec,
                dms=self.dms,
                is_paused=self.is_paused,
                auto_pause=self._auto_pause,
                auto_resume=self._auto_resume,
                flight_cm=self._flight_cm,
            )

            self._tasks["eval"] = loop.create_task(self._eval_loop.run(), name=f"orc-eval-{self.symbol}")
            self._tasks["exits"] = loop.create_task(self._exits_loop.run(), name=f"orc-exits-{self.symbol}")
            self._tasks["watchdog"] = loop.create_task(self._watchdog_loop.run(), name=f"orc-watchdog-{self.symbol}")
            self._tasks["reconcile"] = loop.create_task(self._reconcile_loop(), name=f"orc-reconcile-{self.symbol}")
        finally:
            self._starting = False

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stopping = True
        self._paused = True
        try:
            await asyncio.wait_for(self._wait_drain(), timeout=5.0)
        except asyncio.TimeoutError:
            _log.warning("orchestrator_drain_timeout")
        # остановить внутренние лупы
        self._eval_loop.stop()
        self._exits_loop.stop()
        self._watchdog_loop.stop()
        for t in list(self._tasks.values()):
            if not t.done():
                t.cancel()
        try:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        finally:
            self._tasks.clear()

    def status(self) -> dict:
        return {
            "symbol": self.symbol,
            "running": bool(self._tasks),
            "paused": self._paused,
            "auto_hold": self._auto_hold,
            "tasks": {k: (not v.done()) for k, v in self._tasks.items()},
            "last_beat_ms": self._last_beat_ms,
        }

    async def pause(self) -> None:
        if self._paused:
            return
        self._paused = True
        await self.bus.publish("orchestrator.paused", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)

    async def resume(self) -> None:
        if not self._paused or self._stopping:
            return
        self._paused = False
        self._auto_hold = False
        await self.bus.publish("orchestrator.resumed", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)

    # ---------- helpers ----------
    def is_paused(self) -> bool:
        return self._paused

    async def _auto_pause(self, reason: str, data: Dict[str, str]) -> None:
        if self._auto_hold and self._paused:
            return
        self._paused = True
        self._auto_hold = True
        payload = {"symbol": self.symbol, "reason": reason, "ts_ms": now_ms(), **data}
        await self.bus.publish("orchestrator.auto_paused", payload, key=self.symbol)

    async def _auto_resume(self, reason: str, data: Dict[str, str]) -> None:
        if not self._auto_hold:
            return
        self._auto_hold = False
        self._paused = False
        payload = {"symbol": self.symbol, "reason": reason, "ts_ms": now_ms(), **data}
        await self.bus.publish("orchestrator.auto_resumed", payload, key=self.symbol)

    async def _on_budget_exceeded(self, payload: Dict[str, str]) -> None:
        await self.bus.publish("budget.exceeded", payload, key=self.symbol)
        await self._auto_pause("budget_exceeded", {k: v for k, v in payload.items() if k != "symbol"})

    async def _wait_drain(self) -> None:
        while self._inflight._value < 0:  # type: ignore[attr-defined]
            await asyncio.sleep(0.05)

    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def _flight(self):
        self._inflight.release()
        try:
            yield
        finally:
            try:
                await self._inflight.acquire()
            except Exception:
                pass

    def _flight_cm(self) -> Awaitable:
        # удобный фабричный вызов для передачи в лупы
        return self._flight()

    async def _reconcile_loop(self) -> None:
        while not self._stopping:
            try:
                async with self._flight():
                    try:
                        idem = getattr(self.storage, "idempotency", None)
                        if idem and hasattr(idem, "prune_older_than"):
                            idem.prune_older_than(self.settings.IDEMPOTENCY_TTL_SEC * 10)
                    except Exception:
                        pass
                    try:
                        audit = getattr(self.storage, "audit", None)
                        if audit and hasattr(audit, "prune_older_than"):
                            audit.prune_older_than(days=7)
                    except Exception:
                        pass

                    if not self._paused:
                        if self._recon_orders: await self._recon_orders.run_once()
                        if self._recon_bal:    await self._recon_bal.run_once()
            except Exception as exc:
                _log.error("reconcile_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.reconcile_interval_sec)
