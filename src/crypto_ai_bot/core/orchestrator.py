# core/orchestrator.py (замена целиком)
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Set

from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.metrics import inc, gauge

class Orchestrator:
    """
    Lifecycle + фоновые тики.
    """
    def __init__(
        self,
        *,
        settings: Any,
        broker: Any,
        trades_repo: Any,
        positions_repo: Any,
        exits_repo: Optional[Any],
        idempotency_repo: Optional[Any],
        bus: Any,
        limiter: Optional[Any] = None,
        risk_manager: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.exits_repo = exits_repo
        self.idempotency_repo = idempotency_repo
        self.bus = bus
        self.limiter = limiter
        self.risk_manager = risk_manager

        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        # health/heartbeat
        self._hb_ms: int = int(time.time() * 1000)
        self._last_eval_ms: Optional[int] = None
        self._last_exits_ms: Optional[int] = None
        self._last_reconcile_ms: Optional[int] = None
        self._last_balance_ms: Optional[int] = None
        self._last_latency_ms: Optional[int] = None

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
        self._stop.clear()
        self._tasks.append(asyncio.create_task(self._tick_eval(), name="tick-eval"))
        self._tasks.append(asyncio.create_task(self._tick_exits(), name="tick-exits"))
        self._tasks.append(asyncio.create_task(self._tick_reconcile(), name="tick-reconcile"))
        self._tasks.append(asyncio.create_task(self._tick_balance_and_latency(), name="tick-balance-latency"))
        self._tasks.append(asyncio.create_task(self._tick_watchdog(), name="tick-watchdog"))
        self._tasks.append(asyncio.create_task(self._tick_bus_dlq(), name="tick-bus-dlq"))

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # -------- ticks --------

    async def _tick_eval(self) -> None:
        interval = float(getattr(self.settings, "EVAL_INTERVAL_SEC", 60.0))
        sym = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            t0 = time.time()
            try:
                _ = evaluate_and_maybe_execute(
                    cfg=self.settings,
                    broker=self.broker,
                    trades_repo=self.trades_repo,
                    positions_repo=self.positions_repo,
                    exits_repo=self.exits_repo,
                    idempotency_repo=self.idempotency_repo,
                    limiter=self.limiter,
                    symbol=sym,
                    external=None,
                    bus=self.bus,
                    risk_manager=self.risk_manager,
                )
            except Exception:
                pass
            self._last_eval_ms = int(time.time() * 1000)
            self._hb_ms = self._last_eval_ms
            dt = time.time() - t0
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, interval - dt))
            except asyncio.TimeoutError:
                pass

    async def _tick_exits(self) -> None:
        if not self.exits_repo:
            return
        interval = float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5.0))
        sym = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        list_active = getattr(self.exits_repo, "list_active", None)
        deactivate = getattr(self.exits_repo, "deactivate", None)

        while not self._stop.is_set():
            try:
                rows = list_active(symbol=sym) or [] if callable(list_active) else []
                last_px = 0.0
                if rows:
                    try:
                        t0 = time.time()
                        tkr = self.broker.fetch_ticker(sym)
                        self._last_latency_ms = int((time.time() - t0) * 1000)
                        last_px = float(tkr.get("last") or tkr.get("close") or 0.0)
                        gauge("exchange_latency_ms", self._last_latency_ms, {"op": "fetch_ticker"})
                    except Exception:
                        last_px = 0.0

                for r in rows:
                    kind = str(r.get("kind") or "sl").lower()
                    trig = float(r.get("trigger_px") or 0.0)
                    if last_px > 0.0 and trig > 0.0:
                        fire = (kind == "sl" and last_px <= trig) or (kind == "tp" and last_px >= trig)
                        if fire:
                            _ = place_order(
                                cfg=self.settings,
                                broker=self.broker,
                                trades_repo=self.trades_repo,
                                positions_repo=self.positions_repo,
                                exits_repo=self.exits_repo,
                                symbol=sym,
                                side="sell",
                                idempotency_repo=self.idempotency_repo,
                                bus=self.bus,
                            )
                            if callable(deactivate):
                                try:
                                    deactivate(r.get("id"), executed_ts=int(time.time() * 1000), executed_price=last_px)
                                except Exception:
                                    try:
                                        deactivate(r.get("id"))
                                    except Exception:
                                        pass
                            inc("protective_exits_triggered_total", {"kind": kind, "symbol": sym})
                            if hasattr(self.bus, "publish"):
                                asyncio.create_task(self.bus.publish({
                                    "type": "ExitExecuted",
                                    "symbol": sym,
                                    "ts_ms": int(time.time() * 1000),
                                    "payload": {"kind": kind, "trigger_px": trig, "price": last_px},
                                }))
            except Exception:
                pass
            self._last_exits_ms = int(time.time() * 1000)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_reconcile(self) -> None:
        interval = float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 60.0))
        find_pending = getattr(self.trades_repo, "find_pending_orders", None) or getattr(self.trades_repo, "find_pending", None)
        record_update = getattr(self.trades_repo, "record_exchange_update", None)
        recompute_pos = getattr(self.positions_repo, "recompute_from_trades", None)
        status_map: Dict[str, str] = {
            "open": "pending",
            "closed": "filled",
            "canceled": "canceled",
            "rejected": "rejected",
            "expired": "canceled",
        }
        while not self._stop.is_set():
            changed: Set[str] = set()
            try:
                pend = find_pending(limit=50) or [] if callable(find_pending) else []
                for row in pend:
                    oid = row.get("order_id") or row.get("id") or row.get("exchange_order_id")
                    sym = normalize_symbol(row.get("symbol") or getattr(self.settings, "SYMBOL", "BTC/USDT"))
                    if not oid:
                        continue
                    try:
                        od = self.broker.fetch_order(str(oid), sym)
                    except Exception:
                        continue
                    state = status_map.get(str(od.get("status") or "").lower(), "pending")
                    upd = {
                        "state": state,
                        "filled": float(od.get("filled") or 0.0),
                        "price": float(od.get("price") or 0.0),
                        "cost": float(od.get("cost") or 0.0),
                        "fee": (od.get("fee") or {}),
                        "raw": od,
                        "ts_ms": int(time.time() * 1000),
                    }
                    if callable(record_update):
                        try:
                            record_update(order_id=str(oid), symbol=sym, **upd)
                            changed.add(sym)
                        except Exception:
                            try:
                                record_update(order_id=str(oid), state=upd["state"], raw=upd["raw"])
                                changed.add(sym)
                            except Exception:
                                pass
                if callable(recompute_pos) and changed:
                    for s in changed:
                        try:
                            recompute_pos(symbol=s)
                        except Exception:
                            pass
            except Exception:
                pass
            self._last_reconcile_ms = int(time.time() * 1000)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_balance_and_latency(self) -> None:
        interval = float(getattr(self.settings, "BALANCE_CHECK_INTERVAL_SEC", 300.0))
        if interval <= 0:
            return
        sym = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        base = sym.split("/")[0] if "/" in sym else sym.split(":")[0]
        tol = float(getattr(self.settings, "BALANCE_TOLERANCE", 1e-4))
        get_open = getattr(self.positions_repo, "get_open", None)
        while not self._stop.is_set():
            try:
                # heartbeat + latency ping (очень лёгкий)
                try:
                    t0 = time.time()
                    _ = self.broker.fetch_ticker(sym)
                    self._last_latency_ms = int((time.time() - t0) * 1000)
                    gauge("exchange_latency_ms", self._last_latency_ms, {"op": "ping"})
                except Exception:
                    pass

                # local qty
                local_qty = 0.0
                if callable(get_open):
                    try:
                        rows = get_open() or []
                        for r in rows:
                            if str(r.get("symbol")) == sym:
                                local_qty = float(r.get("qty") or 0.0)
                                break
                    except Exception:
                        local_qty = 0.0
                # exchange qty
                exch_qty = local_qty
                try:
                    bal = self.broker.fetch_balance() or {}
                    total = (bal.get("total") or {})
                    if base in total:
                        exch_qty = float(total.get(base) or 0.0)
                    else:
                        free = (bal.get("free") or {})
                        used = (bal.get("used") or {})
                        exch_qty = float(free.get(base, 0.0)) + float(used.get(base, 0.0))
                except Exception:
                    pass
                drift = abs(exch_qty - local_qty)
                gauge("position_drift", drift, {"symbol": sym})
                if drift > tol and hasattr(self.bus, "publish"):
                    asyncio.create_task(self.bus.publish({
                        "type": "BalanceDriftDetected",
                        "symbol": sym,
                        "ts_ms": int(time.time() * 1000),
                        "payload": {"base": base, "local_qty": local_qty, "exchange_qty": exch_qty, "drift": drift, "tolerance": tol},
                    }))
            except Exception:
                pass
            self._last_balance_ms = int(time.time() * 1000)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_watchdog(self) -> None:
        """
        Простой watchdog: если какой-то тик давно не обновлялся — поднимаем счётчик/ивент.
        """
        stall = float(getattr(self.settings, "WATCHDOG_STALL_SEC", 120.0))
        if stall <= 0:
            return
        while not self._stop.is_set():
            now = int(time.time() * 1000)
            for name, ts in {
                "eval": self._last_eval_ms,
                "exits": self._last_exits_ms,
                "reconcile": self._last_reconcile_ms,
            }.items():
                if ts and (now - ts) > int(stall * 1000):
                    inc("watchdog_stall_total", {"tick": name})
                    if hasattr(self.bus, "publish"):
                        asyncio.create_task(self.bus.publish({
                            "type": "WatchdogStall",
                            "ts_ms": now,
                            "payload": {"tick": name, "age_ms": now - ts},
                        }))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=stall / 2.0)
            except asyncio.TimeoutError:
                pass

    async def _tick_bus_dlq(self) -> None:
        interval = float(getattr(self.settings, "BUS_DLQ_RETRY_SEC", 10.0))
        while not self._stop.is_set():
            try:
                if hasattr(self.bus, "try_republish_from_dlq"):
                    await self.bus.try_republish_from_dlq(limit=50)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
