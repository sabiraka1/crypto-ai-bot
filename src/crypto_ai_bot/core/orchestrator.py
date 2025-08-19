from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Set

from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.brokers.symbols import normalize_symbol
try:
    from crypto_ai_bot.utils.metrics import inc
except Exception:
    def inc(*_args, **_kwargs):  # type: ignore
        pass


class Orchestrator:
    """
    Централизованный lifecycle:
      - tick_eval: оценка + (при необходимости) исполнение
      - tick_exits: мониторинг SL/TP и авто-исполнение защитных выходов
      - tick_reconcile: сверка pending/partial ордеров с биржей и обновление позиций
      - tick_balance: мягкая сверка с фактическим балансом на бирже (только алерт)
      - tick_bus_dlq: репаблиш событий из DLQ
    Все тики «мягкие»: ошибки логируются в своих юзкейсах/репо, оркестратор не падает.
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

    # ---------------- Lifecycle ----------------

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        self._tasks.append(asyncio.create_task(self._tick_eval(), name="tick-eval"))
        self._tasks.append(asyncio.create_task(self._tick_exits(), name="tick-exits"))
        self._tasks.append(asyncio.create_task(self._tick_reconcile(), name="tick-reconcile"))
        self._tasks.append(asyncio.create_task(self._tick_balance(), name="tick-balance"))
        self._tasks.append(asyncio.create_task(self._tick_bus_dlq(), name="tick-bus-dlq"))

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ---------------- Ticks ----------------

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
            dt = time.time() - t0
            wait = max(0.0, interval - dt)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait) if wait > 0 else asyncio.sleep(0)
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
                if not callable(list_active):
                    await asyncio.sleep(interval)
                    continue

                rows = list_active(symbol=sym) or []
                if not rows:
                    await asyncio.sleep(interval)
                    continue

                # текущая цена
                last_px = 0.0
                try:
                    tkr = self.broker.fetch_ticker(sym)
                    last_px = float(tkr.get("last") or tkr.get("close") or 0.0)
                except Exception:
                    last_px = 0.0

                if last_px <= 0.0:
                    await asyncio.sleep(interval)
                    continue

                for r in rows:
                    kind = str(r.get("kind") or "sl").lower()  # sl|tp
                    trig = float(r.get("trigger_px") or 0.0)
                    if trig <= 0.0:
                        continue

                    fire = (kind == "sl" and last_px <= trig) or (kind == "tp" and last_px >= trig)
                    if not fire:
                        continue

                    try:
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
                        if hasattr(self.bus, "publish"):
                            asyncio.create_task(self.bus.publish({
                                "type": "ExitExecuted",
                                "symbol": sym,
                                "ts_ms": int(time.time() * 1000),
                                "payload": {"kind": kind, "trigger_px": trig, "price": last_px},
                            }))
                    except Exception:
                        pass

            except Exception:
                pass

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
                if not callable(find_pending):
                    await asyncio.sleep(interval)
                    continue

                pend = find_pending(limit=50) or []
                if not pend:
                    await asyncio.sleep(interval)
                    continue

                for row in pend:
                    oid = row.get("order_id") or row.get("id") or row.get("exchange_order_id")
                    sym = normalize_symbol(row.get("symbol") or getattr(self.settings, "SYMBOL", "BTC/USDT"))
                    if not oid:
                        continue

                    try:
                        od = self.broker.fetch_order(str(oid), sym)
                    except Exception:
                        continue

                    ostate = str(od.get("status") or "").lower()
                    new_state = status_map.get(ostate, "pending")

                    upd = {
                        "state": new_state,
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
                                record_update(order_id=str(oid), **{k: upd[k] for k in ("state", "raw") if k in upd})
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

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_balance(self) -> None:
        """
        Мягкая сверка локальных позиций с балансом биржи:
        — раз в BALANCE_CHECK_INTERVAL_SEC берём broker.fetch_balance()
        — сравниваем базовый актив для текущего символа с локальной позицией
        — при расхождении > допуск: пишем событие/метрику, НО не лечим автоматически
        """
        interval = float(getattr(self.settings, "BALANCE_CHECK_INTERVAL_SEC", 300.0))
        if interval <= 0:
            return

        sym = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        base = sym.split("/")[0] if "/" in sym else sym.split(":")[0]

        tol = float(getattr(self.settings, "BALANCE_TOLERANCE", 1e-4))  # например, 0.0001 базовой валюты

        get_open = getattr(self.positions_repo, "get_open", None)

        while not self._stop.is_set():
            try:
                # локальное количество по базовому активу
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

                # биржевой баланс
                exch_qty = 0.0
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
                    exch_qty = local_qty  # не шумим без данных

                drift = abs(exch_qty - local_qty)
                if drift > tol:
                    inc("balance_drift_total")
                    if hasattr(self.bus, "publish"):
                        import asyncio
                        asyncio.create_task(self.bus.publish({
                            "type": "BalanceDriftDetected",
                            "symbol": sym,
                            "ts_ms": int(time.time() * 1000),
                            "payload": {
                                "base": base,
                                "local_qty": local_qty,
                                "exchange_qty": exch_qty,
                                "drift": drift,
                                "tolerance": tol,
                            },
                        }))

            except Exception:
                pass

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
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
