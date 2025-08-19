from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.metrics import inc, gauge

log = logging.getLogger(__name__)


class Orchestrator:
    """
    Lifecycle менеджер и фоновые тики (evaluate / exits / reconcile / balance / watchdog / DLQ).
    """

    def __init__(
        self,
        settings: Any,
        broker: Any,
        trades_repo: Any,
        positions_repo: Any,
        exits_repo: Any,
        idempotency_repo: Any,
        bus: Any,
        risk_manager: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.exits_repo = exits_repo
        self.idempotency_repo = idempotency_repo
        self.bus = bus
        self.risk_manager = risk_manager

        self._stop = asyncio.Event()
        self._tasks: Set[asyncio.Task] = set()

        # heartbeats
        self._hb_ms: int = int(time.time() * 1000)
        self._last_eval_ms: int = 0
        self._last_exits_ms: int = 0
        self._last_reconcile_ms: int = 0
        self._last_balance_ms: int = 0
        self._last_latency_ms: int = 0

        try:
            self._symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        except Exception:
            self._symbol = getattr(self.settings, "SYMBOL", "BTC/USDT")

    # -------- public --------

    def health_snapshot(self) -> Dict[str, Any]:
        return {
            "heartbeat_ms": self._hb_ms,
            "last_eval_ms": self._last_eval_ms,
            "last_exits_ms": self._last_exits_ms,
            "last_reconcile_ms": self._last_reconcile_ms,
            "last_balance_ms": self._last_balance_ms,
            "last_latency_ms": self._last_latency_ms,
        }

    async def start(self) -> None:
        if self._tasks:
            return

        # intervals with safe defaults
        eval_sec = float(getattr(self.settings, "EVAL_INTERVAL_SEC", 60.0))
        exits_sec = float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5.0))
        reconcile_sec = float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 60.0))
        bal_lat_sec = float(getattr(self.settings, "BALANCE_LATENCY_INTERVAL_SEC", 300.0))
        watchdog_sec = float(getattr(self.settings, "WATCHDOG_TICK_SEC", 15.0))
        dlq_sec = float(getattr(self.settings, "BUS_DLQ_RETRY_SEC", 10.0))

        self._tasks.update(
            {
                asyncio.create_task(self._loop(self._tick_eval, "eval", eval_sec)),
                asyncio.create_task(self._loop(self._tick_exits, "exits", exits_sec)),
                asyncio.create_task(self._loop(self._tick_reconcile, "reconcile", reconcile_sec)),
                asyncio.create_task(self._loop(self._tick_balance_and_latency, "balance_latency", bal_lat_sec)),
                asyncio.create_task(self._loop(self._tick_watchdog, "watchdog", watchdog_sec)),
                asyncio.create_task(self._loop(self._tick_bus_dlq, "bus_dlq", dlq_sec)),
            }
        )

    async def stop(self) -> None:
        self._stop.set()
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # -------- loop helper --------

    async def _loop(self, tick, name: str, interval: float) -> None:
        while not self._stop.is_set():
            t0 = time.time()
            try:
                await tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("tick %s failed: %s", name, e)
                inc("tick_errors_total", {"tick": name})
            self._hb_ms = int(time.time() * 1000)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(0.0, interval - (time.time() - t0)),
                )
            except asyncio.TimeoutError:
                pass

    # -------- ticks --------

    async def _tick_eval(self) -> None:
        """
        Evaluate signals and maybe execute trade (long-only).
        Kill-switch: если ENABLE_TRADING = False, просто выходим.
        """
        if not bool(getattr(self.settings, "ENABLE_TRADING", True)):
            # Торговые операции заблокированы, но exits/reconcile работают в своих тиках.
            self._last_eval_ms = int(time.time() * 1000)
            gauge("tick_eval_disabled", 1, {"symbol": self._symbol})
            return

        t0 = time.time()
        try:
            await evaluate_and_maybe_execute(
                settings=self.settings,
                broker=self.broker,
                trades_repo=self.trades_repo,
                positions_repo=self.positions_repo,
                exits_repo=self.exits_repo,
                idempotency_repo=self.idempotency_repo,
                symbol=self._symbol,
                external=None,
                bus=self.bus,
                risk_manager=self.risk_manager,
            )
        except Exception as e:
            log.exception("evaluate_and_maybe_execute failed: %s", e)
            inc("evaluate_errors_total", {"symbol": self._symbol})
        finally:
            self._last_eval_ms = int(time.time() * 1000)
            dt = self._last_eval_ms / 1000 - t0
            gauge("tick_eval_duration_sec", dt, {"symbol": self._symbol})

    async def _tick_exits(self) -> None:
        await self._tick_exits_once()
        self._last_exits_ms = int(time.time() * 1000)

    async def _tick_reconcile(self) -> None:
        await self._tick_reconcile_once()
        self._last_reconcile_ms = int(time.time() * 1000)

    async def _tick_balance_and_latency(self) -> None:
        try:
            t0 = time.time()
            bal = await asyncio.to_thread(self.broker.fetch_balance)
            latency = (time.time() - t0)
            self._last_balance_ms = int(t0 * 1000)
            self._last_latency_ms = int(latency * 1000)
            gauge("balance_latency_ms", self._last_latency_ms, {"symbol": self._symbol})
            if hasattr(self.bus, "publish"):
                await self.bus.publish(
                    {
                        "type": "BalanceSampled",
                        "ts_ms": self._last_balance_ms,
                        "latency_ms": self._last_latency_ms,
                        "free": getattr(bal, "free", {}) if hasattr(bal, "free") else (bal.get("free") if isinstance(bal, dict) else {}),
                    }
                )
        except Exception as e:
            log.debug("balance/latency tick failed: %s", e)

    async def _tick_watchdog(self) -> None:
        stall = float(getattr(self.settings, "WATCHDOG_STALL_SEC", 120.0))
        if stall <= 0:
            return
        gauge("watchdog_stall_budget_ms", int(stall * 1000), {})
        while not self._stop.is_set():
            now = int(time.time() * 1000)
            for name, ts in (
                ("eval", self._last_eval_ms),
                ("exits", self._last_exits_ms),
                ("reconcile", self._last_reconcile_ms),
            ):
                if ts and (now - ts) > int(stall * 1000):
                    inc("watchdog_stall_total", {"tick": name})
                    if hasattr(self.bus, "publish"):
                        asyncio.create_task(
                            self.bus.publish(
                                {"type": "WatchdogStall", "ts_ms": now, "tick": name, "lag_ms": (now - ts)}
                            )
                        )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def _tick_bus_dlq(self) -> None:
        try:
            interval = float(getattr(self.settings, "BUS_DLQ_RETRY_SEC", 10.0))
        except Exception:
            interval = 10.0
        while not self._stop.is_set():
            try:
                if hasattr(self.bus, "try_republish_from_dlq"):
                    await self.bus.try_republish_from_dlq(limit=50)
            except Exception as e:
                log.debug("DLQ replay error: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # -------- single-iteration helpers (для CLI-обёрток) --------

    async def _tick_exits_once(self) -> None:
        try:
            if not hasattr(self.exits_repo, "list_active"):
                return
            exits = self.exits_repo.list_active(symbol=self._symbol)
            if not exits:
                return

            ticker = await asyncio.to_thread(self.broker.fetch_ticker, self._symbol)
            last_px = float(ticker.get("last") or ticker.get("close") or 0.0)

            for ex in exits:
                trig = float(ex.get("trigger_px") or 0.0)
                kind = ex.get("kind")
                hit = (kind == "sl" and last_px <= trig) or (kind == "tp" and last_px >= trig)
                if not hit:
                    continue

                qty = float(ex.get("qty") or 0.0)
                if qty <= 0.0:
                    pos = self.positions_repo.get(self._symbol) if hasattr(self.positions_repo, "get") else None
                    qty = float(pos.get("qty") or 0.0) if isinstance(pos, dict) else float(getattr(pos, "qty", 0.0) or 0.0)

                if qty > 0.0:
                    try:
                        await asyncio.to_thread(
                            self.broker.create_order,
                            self._symbol,
                            "market",
                            "sell",
                            qty,
                            None,
                            {"text": None},
                        )
                        inc("protective_exit_executed_total", {"symbol": self._symbol, "kind": kind})
                    finally:
                        pass

                if hasattr(self.exits_repo, "deactivate") and ex.get("id") is not None:
                    self.exits_repo.deactivate(ex["id"])

        except Exception as e:
            log.exception("tick_exits_once failed: %s", e)

    async def _tick_reconcile_once(self) -> None:
        try:
            if hasattr(self.trades_repo, "find_pending_orders"):
                pend = self.trades_repo.find_pending_orders()
            elif hasattr(self.trades_repo, "find_pending"):
                pend = self.trades_repo.find_pending()
            else:
                return

            if not pend:
                return

            for od in pend:
                oid = od.get("order_id") or od.get("id")
                if not oid:
                    continue
                ex_od = await asyncio.to_thread(self.broker.fetch_order, oid, self._symbol)
                if hasattr(self.trades_repo, "record_exchange_update"):
                    self.trades_repo.record_exchange_update(oid, ex_od)
                elif hasattr(self.trades_repo, "record_update"):
                    self.trades_repo.record_update(oid, raw=ex_od)
                inc("reconcile_updates_total", {"symbol": self._symbol})

        except Exception as e:
            log.exception("tick_reconcile_once failed: %s", e)
