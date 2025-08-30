# src/crypto_ai_bot/core/application/orchestrator.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional, TYPE_CHECKING

from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.application.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.application.reconciliation.balances import BalancesReconciler
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms

if TYPE_CHECKING:
    from crypto_ai_bot.core.infrastructure.settings import Settings

_log = get_logger("orchestrator")


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

    eval_interval_sec: float = 60.0
    exits_interval_sec: float = 5.0
    reconcile_interval_sec: float = 60.0
    watchdog_interval_sec: float = 15.0

    force_eval_action: Optional[str] = None
    dms_timeout_ms: int = 120_000

    _tasks: Dict[str, asyncio.Task] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _last_beat_ms: int = field(default=0, init=False)
    _paused: bool = field(default=False, init=False)

    _dms: Optional[DeadMansSwitch] = field(default=None, init=False)
    _recon_orders: Optional[OrdersReconciler] = field(default=None, init=False)
    _recon_bal: Optional[BalancesReconciler] = field(default=None, init=False)

    # simple in-flight guard
    _inflight: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(0), init=False)

    # ------------ lifecycle ------------
    def start(self) -> None:
        if self._tasks:
            return
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

        self._dms = DeadMansSwitch(self.storage, self.broker, self.symbol, timeout_ms=self.dms_timeout_ms)
        self._recon_orders = OrdersReconciler(self.broker, self.symbol)
        self._recon_bal = BalancesReconciler(self.broker, self.symbol)

        self._tasks["eval"] = loop.create_task(self._eval_loop(), name="orc-eval")
        self._tasks["exits"] = loop.create_task(self._exits_loop(), name="orc-exits")
        self._tasks["reconcile"] = loop.create_task(self._reconcile_loop(), name="orc-reconcile")
        self._tasks["watchdog"] = loop.create_task(self._watchdog_loop(), name="orc-watchdog")

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stopping = True
        self._paused = True
        try:
            await asyncio.wait_for(self._wait_drain(), timeout=5.0)
        except asyncio.TimeoutError:
            _log.warning("orchestrator_drain_timeout")
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
            "paused": self._paused,
            "tasks": {k: (not v.done()) for k, v in self._tasks.items()},
            "last_beat_ms": self._last_beat_ms,
        }

    async def pause(self) -> None:
        if self._paused:
            return
        self._paused = True
        await self.bus.publish("orchestrator.paused", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)
        _log.info("orchestrator_paused")

    async def resume(self) -> None:
        if not self._paused or self._stopping:
            return
        self._paused = False
        await self.bus.publish("orchestrator.resumed", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)
        _log.info("orchestrator_resumed")

    # ------------ internals ------------
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

    # ------------ loops ------------
    async def _eval_loop(self) -> None:
        while not self._stopping:
            try:
                if self._paused:
                    await asyncio.sleep(min(1.0, self.eval_interval_sec))
                else:
                    async with self._flight():
                        await eval_and_execute(
                            symbol=self.symbol,
                            storage=self.storage,
                            broker=self.broker,
                            bus=self.bus,
                            exchange=self.settings.EXCHANGE,
                            fixed_quote_amount=dec(str(self.settings.FIXED_AMOUNT)),
                            idempotency_bucket_ms=self.settings.IDEMPOTENCY_BUCKET_MS,
                            idempotency_ttl_sec=self.settings.IDEMPOTENCY_TTL_SEC,
                            force_action=self.force_eval_action,
                            risk_manager=self.risk,
                            protective_exits=self.exits,
                            settings=self.settings,
                            fee_estimate_pct=self.settings.FEE_PCT_ESTIMATE,
                        )
                        if self._dms:
                            self._dms.beat()
            except Exception as exc:
                _log.error("tick_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.eval_interval_sec)

    async def _exits_loop(self) -> None:
        while not self._stopping:
            try:
                if self._paused:
                    await asyncio.sleep(min(1.0, self.exits_interval_sec))
                else:
                    async with self._flight():
                        pos = self.storage.positions.get_position(self.symbol)
                        if pos.base_qty and pos.base_qty > 0:
                            await self.exits.ensure(symbol=self.symbol)
                            check_exec = getattr(self.exits, "check_and_execute", None)
                            if callable(check_exec):
                                try:
                                    order = await check_exec(symbol=self.symbol)
                                    if order:
                                        _log.info("exit_executed", extra={"symbol": self.symbol, "side": order.side, "client_order_id": order.client_order_id})
                                except Exception as exc:
                                    _log.error("check_and_execute_failed", extra={"error": str(exc)})
            except Exception as exc:
                _log.error("ensure_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.exits_interval_sec)

    async def _reconcile_loop(self) -> None:
        while not self._stopping:
            try:
                async with self._flight():
                    # обслуживание хранилищ
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

                    # сверки (в паузе — только обслуживание)
                    if not self._paused:
                        if getattr(self, "_recon_orders", None):
                            await self._recon_orders.run_once()
                        if getattr(self, "_recon_bal", None):
                            await self._recon_bal.run_once()

                        # позиционная сверка
                        try:
                            pos = self.storage.positions.get_position(self.symbol)
                            balance = await self.broker.fetch_balance(self.symbol)
                            diff = Decimal(str(balance.free_base)) - Decimal(str(pos.base_qty or dec("0")))
                            if abs(diff) > Decimal("0.00000001"):
                                _log.warning("position_discrepancy", extra={"symbol": self.symbol, "local": str(pos.base_qty), "exchange": str(balance.free_base)})
                                await self.bus.publish(
                                    "reconcile.position_mismatch",
                                    {"symbol": self.symbol, "local": str(pos.base_qty), "exchange": str(balance.free_base)},
                                    key=self.symbol,
                                )
                                if bool(getattr(self.settings, "RECONCILE_AUTOFIX", 0)):
                                    add_rec = getattr(self.storage.trades, "add_reconciliation_trade", None)
                                    if callable(add_rec):
                                        add_rec({"symbol": self.symbol, "side": ("buy" if diff > 0 else "sell"), "amount": str(abs(diff)), "status": "reconciliation",
                                                 "ts_ms": now_ms(), "client_order_id": f"reconcile-{self.symbol}-{now_ms()}"} )
                                    self.storage.positions.set_base_qty(self.symbol, dec(str(balance.free_base)))
                        except Exception as exc:
                            _log.error("position_reconcile_failed", extra={"error": str(exc)})

                        # --- НОВОЕ: обогащение недостающих комиссий ---
                        try:
                            # настройки с дефолтами
                            lookback_min = int(getattr(self.settings, "ENRICH_TRADES_LOOKBACK_MIN", 180))
                            batch_limit = int(getattr(self.settings, "ENRICH_TRADES_BATCH", 50))
                            since = now_ms() - lookback_min * 60_000
                            missing = self.storage.trades.list_missing_fees(self.symbol, since, batch_limit)
                            if missing and hasattr(self.broker, "fetch_order_trades"):
                                # подгружаем мои сделки по символу
                                trades = await getattr(self.broker, "fetch_order_trades")(self.symbol, since_ms=since, limit=200)
                                if trades:
                                    quote = parse_symbol(self.symbol).quote
                                    # индексируем по orderId
                                    by_order: Dict[str, list] = {}
                                    for tr in trades:
                                        oid = str(tr.get("order") or tr.get("orderId") or "")
                                        if not oid:
                                            continue
                                        by_order.setdefault(oid, []).append(tr)
                                    for row in missing:
                                        row_id = int(row["id"])
                                        oid = str(row.get("broker_order_id") or "")  # может быть пусто
                                        fee_total = dec("0")
                                        price, cost = dec(str(row.get("price") or "0")), dec(str(row.get("cost") or "0"))
                                        if oid and oid in by_order:
                                            for tr in by_order[oid]:
                                                fee_total += dec(str(self._extract_trade_fee(tr, quote)))
                                            # уточним price/cost, если пришли исполняемые trades
                                            # (по рынку цена может быть не задана в исходном ордере)
                                            try:
                                                px = dec(str(trades[-1].get("price") or price))
                                                cs = sum(dec(str(t.get("cost") or 0)) for t in by_order[oid]) or cost
                                                if cs > 0:
                                                    self.storage.trades.update_price_cost_by_id(row_id, px, cs)
                                            except Exception:
                                                pass
                                        elif hasattr(self.broker, "fetch_order_safe") and oid:
                                            # fallback: подтянуть ордер и посчитать fee
                                            o = await getattr(self.broker, "fetch_order_safe")(oid, self.symbol)
                                            if o:
                                                fee_total = dec(str(self._extract_trade_fee(o, quote)))
                                        if fee_total > 0:
                                            self.storage.trades.set_fee_by_id(row_id, fee_total)
                        except Exception as exc:
                            _log.error("enrich_fees_failed", extra={"error": str(exc)})

            except Exception as exc:
                _log.error("reconcile_failed", extra={"error": str(exc)})
            await asyncio.sleep(self.reconcile_interval_sec)

    # helper to get fee from a trade/order dict in quote ccy
    def _extract_trade_fee(self, d: dict, quote_ccy: str) -> Decimal:
        fee = d.get("fee"); total = dec("0")
        if fee and str(fee.get("currency") or "").upper() == quote_ccy:
            try: total += dec(fee.get("cost") or 0)
            except Exception: pass
        fees = d.get("fees") or []
        for f in fees:
            if str(f.get("currency") or "").upper() == quote_ccy:
                try: total += dec(f.get("cost") or 0)
                except Exception: pass
        return total
