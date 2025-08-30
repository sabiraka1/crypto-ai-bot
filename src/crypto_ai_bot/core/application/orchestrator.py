from __future__ import annotations

import asyncio, os
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
from crypto_ai_bot.utils import metrics as M

if TYPE_CHECKING:
    from crypto_ai_bot.core.infrastructure.settings import Settings

_log = get_logger("orchestrator")


def _fixed_amount_for(settings: "Settings", symbol: str) -> Decimal:
    """ENV-переопределение фиксированной суммы по символу: AMOUNT_<BASE>_<QUOTE>."""
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
    _auto_hold: bool = field(default=False, init=False)

    _dms: Optional[DeadMansSwitch] = field(default=None, init=False)
    _recon_orders: Optional[OrdersReconciler] = field(default=None, init=False)
    _recon_bal: Optional[BalancesReconciler] = field(default=None, init=False)

    _inflight: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(0), init=False)

    def start(self) -> None:
        if self._tasks: return
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

        # RiskManager теперь знает Storage
        try:
            self.risk.attach_storage(self.storage)
        except Exception:
            pass

        self._dms = DeadMansSwitch(self.storage, self.broker, self.symbol, timeout_ms=self.dms_timeout_ms)
        self._recon_orders = OrdersReconciler(self.broker, self.symbol)
        self._recon_bal = BalancesReconciler(self.broker, self.symbol)

        self._tasks["eval"] = loop.create_task(self._eval_loop(), name=f"orc-eval-{self.symbol}")
        self._tasks["exits"] = loop.create_task(self._exits_loop(), name=f"orc-exits-{self.symbol}")
        self._tasks["reconcile"] = loop.create_task(self._reconcile_loop(), name=f"orc-reconcile-{self.symbol}")
        self._tasks["watchdog"] = loop.create_task(self._watchdog_loop(), name=f"orc-watchdog-{self.symbol}")

    async def stop(self) -> None:
        if not self._tasks: return
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
            "symbol": self.symbol,
            "running": bool(self._tasks),
            "paused": self._paused,
            "auto_hold": self._auto_hold,
            "tasks": {k: (not v.done()) for k, v in self._tasks.items()},
            "last_beat_ms": self._last_beat_ms,
        }

    async def pause(self) -> None:
        if self._paused: return
        self._paused = True
        await self.bus.publish("orchestrator.paused", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)

    async def resume(self) -> None:
        if not self._paused or self._stopping: return
        self._paused = False
        self._auto_hold = False
        await self.bus.publish("orchestrator.resumed", {"symbol": self.symbol, "ts_ms": now_ms()}, key=self.symbol)

    async def _auto_pause(self, reason: str, data: Dict[str, str]) -> None:
        if self._auto_hold and self._paused: return
        self._paused = True
        self._auto_hold = True
        payload = {"symbol": self.symbol, "reason": reason, "ts_ms": now_ms(), **data}
        await self.bus.publish("orchestrator.auto_paused", payload, key=self.symbol)

    async def _auto_resume(self, reason: str, data: Dict[str, str]) -> None:
        if not self._auto_hold: return
        self._auto_hold = False
        self._paused = False
        payload = {"symbol": self.symbol, "reason": reason, "ts_ms": now_ms(), **data}
        await self.bus.publish("orchestrator.auto_resumed", payload, key=self.symbol)

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

    def _budget_exceeded(self) -> Optional[Dict[str, str]]:
        max_orders_5m = float(getattr(self.settings, "BUDGET_MAX_ORDERS_5M", 0) or 0)
        if max_orders_5m > 0:
            cnt5 = self.storage.trades.count_orders_last_minutes(self.symbol, 5)
            if cnt5 >= max_orders_5m:
                return {"type": "max_orders_5m", "count_5m": str(cnt5), "limit": str(int(max_orders_5m))}
        max_turnover = Decimal(str(getattr(self.settings, "BUDGET_MAX_TURNOVER_DAY_QUOTE", "0") or "0"))
        if max_turnover > 0:
            day_turn = self.storage.trades.daily_turnover_quote(self.symbol)
            if day_turn >= max_turnover:
                return {"type": "max_turnover_day", "turnover": str(day_turn), "limit": str(max_turnover)}
        return None

    def _budget_ok(self) -> bool:
        max_orders_5m = float(getattr(self.settings, "BUDGET_MAX_ORDERS_5M", 0) or 0)
        if max_orders_5m > 0:
            if self.storage.trades.count_orders_last_minutes(self.symbol, 5) >= max_orders_5m:
                return False
        max_turnover = Decimal(str(getattr(self.settings, "BUDGET_MAX_TURNOVER_DAY_QUOTE", "0") or "0"))
        if max_turnover > 0:
            if self.storage.trades.daily_turnover_quote(self.symbol) >= max_turnover:
                return False
        return True

    async def _eval_loop(self) -> None:
        while not self._stopping:
            try:
                if self._paused:
                    await asyncio.sleep(min(1.0, self.eval_interval_sec))
                else:
                    over = self._budget_exceeded()
                    if over:
                        await self._auto_pause("budget_exceeded", over)
                        await asyncio.sleep(self.eval_interval_sec)
                        continue

                    async with self._flight():
                        fixed_amt = _fixed_amount_for(self.settings, self.symbol)
                        await eval_and_execute(
                            symbol=self.symbol,
                            storage=self.storage,
                            broker=self.broker,
                            bus=self.bus,
                            exchange=self.settings.EXCHANGE,
                            fixed_quote_amount=fixed_amt,
                            idempotency_bucket_ms=self.settings.IDEMPOTENCY_BUCKET_MS,
                            idempotency_ttl_sec=self.settings.IDEMPOTENCY_TTL_SEC,
                            force_action=self.force_eval_action,
                            risk_manager=self.risk,
                            protective_exits=self.exits,
                            settings=self.settings,
                            fee_estimate_pct=self.settings.FEE_PCT_ESTIMATE,
                        )
                        if getattr(self, "_dms", None):
                            self._dms.beat()
            except Exception as exc:
                _log.error("tick_failed", extra={"error": str(exc), "symbol": self.symbol})
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
                                    await check_exec(symbol=self.symbol)
                                except Exception as exc:
                                    _log.error("check_and_execute_failed", extra={"error": str(exc), "symbol": self.symbol})
            except Exception as exc:
                _log.error("ensure_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.exits_interval_sec)

    async def _reconcile_loop(self) -> None:
        while not self._stopping:
            try:
                async with self._flight():
                    try:
                        prune = getattr(self.storage.idempotency, "prune_older_than", None)
                        if callable(prune): prune(self.settings.IDEMPOTENCY_TTL_SEC * 10)
                    except Exception: pass
                    try:
                        prune_audit = getattr(self.storage.audit, "prune_older_than", None)
                        if callable(prune_audit): prune_audit(days=7)
                    except Exception: pass

                    if not self._paused:
                        if getattr(self, "_recon_orders", None): await self._recon_orders.run_once()
                        if getattr(self, "_recon_bal", None):    await self._recon_bal.run_once()
            except Exception as exc:
                _log.error("reconcile_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.reconcile_interval_sec)

    async def _watchdog_loop(self) -> None:
        err_pause = float(getattr(self.settings, "AUTO_PAUSE_ERROR_RATE_5M", 0.50))
        err_resume = float(getattr(self.settings, "AUTO_RESUME_ERROR_RATE_5M", 0.20))
        lat_pause = float(getattr(self.settings, "AUTO_PAUSE_LATENCY_MS_5M", 2000.0))
        lat_resume = float(getattr(self.settings, "AUTO_RESUME_LATENCY_MS_5M", 1000.0))
        win = 5 * 60

        while not self._stopping:
            try:
                async with self._flight():
                    rep = await self.health.check(symbol=self.symbol)
                    hb = parse_symbol(self.symbol).base + "/" + parse_symbol(self.symbol).quote
                    await self.bus.publish("watchdog.heartbeat", {"ok": rep.ok, "symbol": hb}, key=hb)
                    self._last_beat_ms = rep.ts_ms

                    labels = {}
                    er = M.error_rate(labels, win)
                    al = M.avg_latency_ms(labels, win)

                    if (er >= err_pause) or (al >= lat_pause):
                        await self._auto_pause("sla_threshold_exceeded",
                                               {"error_rate_5m": f"{er:.4f}", "avg_latency_ms_5m": f"{al:.2f}"})
                    elif self._auto_hold and (er <= err_resume) and (al <= lat_resume) and self._budget_ok():
                        await self._auto_resume("sla_stabilized_and_budget_ok",
                                                {"error_rate_5m": f"{er:.4f}", "avg_latency_ms_5m": f"{al:.2f}"})
                    elif self._auto_hold and self._budget_ok() and (er < err_pause) and (al < lat_pause):
                        await self._auto_resume("budget_ok", {"error_rate_5m": f"{er:.4f}", "avg_latency_ms_5m": f"{al:.2f}"})

            except Exception as exc:
                _log.error("watchdog_failed", extra={"error": str(exc), "symbol": self.symbol})
            await asyncio.sleep(self.watchdog_interval_sec)
