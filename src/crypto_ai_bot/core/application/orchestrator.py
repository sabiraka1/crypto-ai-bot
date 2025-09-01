# src/crypto_ai_bot/core/application/orchestrator.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe
from crypto_ai_bot.utils.trace import cid_context, get_cid

_log = get_logger("orchestrator")

LoopFn = Callable[[], Awaitable[None]]


@dataclass
class LoopSpec:
    name: str
    interval_sec: float
    enabled: bool
    runner: LoopFn
    task: asyncio.Task[None] | None = None
    paused: bool = False


@dataclass
class Orchestrator:
    symbol: str
    storage: Any
    broker: Any
    bus: Any
    risk: Any
    exits: Any
    health: Any
    settings: Any
    dms: Any

    _loops: dict[str, LoopSpec] = field(default_factory=dict)
    _started: bool = False
    _paused: bool = False

    def __post_init__(self) -> None:
        s = self.settings

        def _loop(coro: Callable[[], Awaitable[None]], interval: float, enabled: bool, name: str) -> LoopSpec:
            return LoopSpec(name=name, interval_sec=float(interval), enabled=bool(enabled), runner=coro)

        self._loops = {
            "eval": _loop(self._eval_loop, getattr(s, "EVAL_INTERVAL_SEC", 5.0), getattr(s, "EVAL_ENABLED", True), "eval"),
            "exits": _loop(self._exits_loop, getattr(s, "EXITS_INTERVAL_SEC", 5.0), getattr(s, "EXITS_ENABLED", False), "exits"),
            "reconcile": _loop(self._reconcile_loop, getattr(s, "RECONCILE_INTERVAL_SEC", 15.0), getattr(s, "RECONCILE_ENABLED", True), "reconcile"),
            "watchdog": _loop(self._watchdog_loop, getattr(s, "WATCHDOG_INTERVAL_SEC", 10.0), getattr(s, "WATCHDOG_ENABLED", True), "watchdog"),
            "settlement": _loop(self._settlement_loop, getattr(s, "SETTLEMENT_INTERVAL_SEC", 7.0), getattr(s, "SETTLEMENT_ENABLED", True), "settlement"),
        }

    # ---------------------------
    # Публичное API
    # ---------------------------
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._paused = False
        for spec in self._loops.values():
            if not spec.enabled:
                continue
            spec.task = asyncio.create_task(self._loop_runner(spec))
        payload = {"symbol": self.symbol, "reason": "start"}
        cid = get_cid()
        if cid: payload["cid"] = cid
        await self.bus.publish("orchestrator.auto_resumed", payload)
        _log.info("orchestrator_started", extra={"symbol": self.symbol})

    async def stop(self) -> None:
        for spec in self._loops.values():
            if spec.task and not spec.task.done():
                spec.task.cancel()
        self._started = False
        self._paused = False
        payload = {"symbol": self.symbol, "reason": "stop"}
        cid = get_cid()
        if cid: payload["cid"] = cid
        await self.bus.publish("orchestrator.auto_paused", payload)
        _log.info("orchestrator_stopped", extra={"symbol": self.symbol})

    async def pause(self) -> None:
        if not self._started or self._paused:
            return
        self._paused = True
        payload = {"symbol": self.symbol, "reason": "manual"}
        cid = get_cid()
        if cid: payload["cid"] = cid
        await self.bus.publish("orchestrator.auto_paused", payload)
        _log.info("orchestrator_paused", extra={"symbol": self.symbol})

    async def resume(self) -> None:
        if not self._started or not self._paused:
            return
        self._paused = False
        payload = {"symbol": self.symbol, "reason": "manual"}
        cid = get_cid()
        if cid: payload["cid"] = cid
        await self.bus.publish("orchestrator.auto_resumed", payload)
        _log.info("orchestrator_resumed", extra={"symbol": self.symbol})

    def status(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "paused": self._paused,
            "loops": {
                name: {
                    "enabled": spec.enabled,
                    "paused": spec.paused,
                    "interval_sec": spec.interval_sec,
                    "task_alive": bool(spec.task and not spec.task.done()),
                }
                for name, spec in self._loops.items()
            },
        }

    # ---------------------------
    # Внутреннее: единый раннер цикла
    # ---------------------------
    async def _loop_runner(self, spec: LoopSpec) -> None:
        loop = asyncio.get_event_loop()
        while self._started and spec.enabled:
            if self._paused or spec.paused:
                await asyncio.sleep(spec.interval_sec)
                continue
            try:
                with cid_context():  # ← генерируем CID на каждую итерацию
                    t0 = loop.time()
                    await spec.runner()
                    dt_ms = (loop.time() - t0) * 1000.0
                    observe("orchestrator.loop.ms", dt_ms, {"loop": spec.name, "symbol": self.symbol})
                    inc("orchestrator_loop_ok_total", loop=spec.name, symbol=self.symbol)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.error("loop_failed", extra={"loop": spec.name, "error": str(exc)})
                inc("orchestrator_loop_failed_total", loop=spec.name, symbol=self.symbol)
                await asyncio.sleep(max(0.5, spec.interval_sec))
            await asyncio.sleep(max(0.001, spec.interval_sec))

    # ---------------------------
    # Конкретные циклы
    # ---------------------------
    async def _eval_loop(self) -> None:
        try:
            from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute
            await eval_and_execute(
                symbol=self.symbol,
                storage=self.storage,
                broker=self.broker,
                bus=self.bus,
                risk=self.risk,
                exits=self.exits,
                settings=self.settings,
            )
        except Exception as exc:
            _log.error("eval_loop_error", extra={"error": str(exc)})
            raise

    async def _exits_loop(self) -> None:
        try:
            await self.exits.tick(self.symbol)
        except Exception as exc:
            _log.error("exits_loop_error", extra={"error": str(exc)})
            raise

    async def _reconcile_loop(self) -> None:
        try:
            from crypto_ai_bot.core.application.reconciliation.balances import reconcile_balances
            from crypto_ai_bot.core.application.reconciliation.positions import reconcile_positions
            await reconcile_positions(self.symbol, self.storage, self.broker, self.bus, self.settings)
            await reconcile_balances(self.symbol, self.storage, self.broker, self.bus, self.settings)
        except Exception as exc:
            _log.error("reconcile_loop_error", extra={"error": str(exc)})
            raise

    async def _watchdog_loop(self) -> None:
        try:
            await self.health.tick(self.symbol, dms=self.dms)
        except Exception as exc:
            _log.error("watchdog_loop_error", extra={"error": str(exc)})
            raise

    async def _settlement_loop(self) -> None:
        try:
            from crypto_ai_bot.core.application.use_cases.partial_fills import settle_orders
            await settle_orders(self.symbol, self.storage, self.broker, self.bus, self.settings)
        except Exception as exc:
            _log.error("settlement_loop_error", extra={"error": str(exc)})
            raise
