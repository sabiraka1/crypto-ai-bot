# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from crypto_ai_bot.utils.metrics import inc, observe_histogram, set_gauge
from crypto_ai_bot.core._time import now_ms
from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute

# По возможности импортируем use-case защитных выходов (не обязателен)
try:
    from crypto_ai_bot.core.use_cases.protective_exits import run_protective_exits_check
except Exception:  # pragma: no cover
    run_protective_exits_check = None  # type: ignore


class Orchestrator:
    """
    Управляет жизненным циклом:
      - периодическая оценка и исполнение сделок
      - проверка защитных выходов (SL/TP)
      - reconcile открытых ордеров
      - проверка баланса/latency к бирже
      - watchdog на «залипание»
      - корректный graceful shutdown
    """

    def __init__(self, *, container: Any, logger: Optional[logging.Logger] = None) -> None:
        self.c = container
        self.cfg = container.settings
        self.log = logger or logging.getLogger("orchestrator")

        # интервалы (сек)
        self.eval_interval = float(getattr(self.cfg, "EVAL_INTERVAL_SEC", 60.0))
        self.exits_interval = float(getattr(self.cfg, "EXITS_INTERVAL_SEC", 5.0))
        self.reconcile_interval = float(getattr(self.cfg, "RECONCILE_INTERVAL_SEC", 60.0))
        self.balance_interval = float(getattr(self.cfg, "BALANCE_INTERVAL_SEC", 300.0))
        self.watchdog_interval = float(getattr(self.cfg, "WATCHDOG_INTERVAL_SEC", 15.0))
        self.watchdog_stall_sec = float(getattr(self.cfg, "WATCHDOG_STALL_SEC", 120.0))

        # runtime
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._last_eval_ms = now_ms()
        self._last_reconcile_ms = now_ms()
        self._last_exits_ms = now_ms()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.log.info("Orchestrator starting...")

        # Старт фоновых тикеров
        self._tasks = [
            asyncio.create_task(self._tick_eval(), name="tick_eval"),
            asyncio.create_task(self._tick_exits(), name="tick_exits"),
            asyncio.create_task(self._tick_reconcile(), name="tick_reconcile"),
            asyncio.create_task(self._tick_balance_and_latency(), name="tick_balance"),
            asyncio.create_task(self._tick_watchdog(), name="tick_watchdog"),
        ]
        self.log.info("Orchestrator started with %d tasks", len(self._tasks))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.log.info("Orchestrator stopping...")

        for t in self._tasks:
            t.cancel()
        # корректно ждём завершения
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        finally:
            self._tasks.clear()

        self.log.info("Orchestrator stopped")

    # ---------------------- Ticks ----------------------

    async def _tick_eval(self) -> None:
        """Оценка сигналов и, при необходимости, исполнение."""
        sym = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        while self._running:
            t0 = now_ms()
            try:
                await evaluate_and_maybe_execute(
                    symbol=sym,
                    cfg=self.cfg,
                    broker=self.c.broker,
                    positions_repo=self.c.positions_repo,
                    trades_repo=self.c.trades_repo,
                    exits_repo=getattr(self.c, "exits_repo", None),
                    idempotency_repo=self.c.idempotency_repo,
                    bus=self.c.bus,
                    external=getattr(self.c, "external", None),
                )
                self._last_eval_ms = now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("evaluate_and_maybe_execute failed: %s", e)
                inc("orchestrator_tick_errors_total", {"tick": "eval"})
            finally:
                dt = (now_ms() - t0) / 1000.0
                observe_histogram("tick_eval_seconds", dt, {"symbol": sym})
                await asyncio.sleep(self.eval_interval)

    async def _tick_exits(self) -> None:
        """Мониторинг и исполнение защитных выходов (SL/TP)."""
        if run_protective_exits_check is None:
            # use-case не доступен — тихо пропускаем
            return
        sym = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        while self._running:
            t0 = now_ms()
            try:
                await run_protective_exits_check(
                    cfg=self.cfg,
                    broker=self.c.broker,
                    positions_repo=self.c.positions_repo,
                    exits_repo=getattr(self.c, "exits_repo", None),
                    trades_repo=self.c.trades_repo,
                    bus=self.c.bus,
                )
                self._last_exits_ms = now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("protective_exits check failed: %s", e)
                inc("orchestrator_tick_errors_total", {"tick": "exits"})
            finally:
                dt = (now_ms() - t0) / 1000.0
                observe_histogram("tick_exits_seconds", dt, {"symbol": sym})
                await asyncio.sleep(self.exits_interval)

    async def _tick_reconcile(self) -> None:
        """Сверка открытых ордеров и обновление их статусов."""
        sym = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        while self._running:
            t0 = now_ms()
            try:
                repo = self.c.trades_repo
                if hasattr(repo, "reconcile_open_orders"):
                    await repo.reconcile_open_orders(broker=self.c.broker, bus=self.c.bus)
                self._last_reconcile_ms = now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("reconcile failed: %s", e)
                inc("orchestrator_tick_errors_total", {"tick": "reconcile"})
            finally:
                dt = (now_ms() - t0) / 1000.0
                observe_histogram("tick_reconcile_seconds", dt, {"symbol": sym})
                await asyncio.sleep(self.reconcile_interval)

    async def _tick_balance_and_latency(self) -> None:
        """Проверка баланса/latency к бирже (для health/метрик)."""
        ex = getattr(self.cfg, "EXCHANGE", "gateio")
        sym = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        while self._running:
            t0 = now_ms()
            try:
                # измерим latency на лёгком вызове
                t1 = now_ms()
                _ = self.c.broker.fetch_ticker(sym)
                lat = (now_ms() - t1) / 1000.0
                set_gauge("exchange_latency_seconds", lat, {"exchange": ex})

                # баланс (не критично, но полезно для health)
                if hasattr(self.c.broker, "fetch_balance"):
                    bal = self.c.broker.fetch_balance()
                    if isinstance(bal, dict) and "total" in bal:
                        # например, выставим USDT баланс (если есть)
                        usdt = bal["total"].get("USDT")
                        if usdt is not None:
                            set_gauge("balance_total_usdt", float(usdt), {"exchange": ex})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("balance/latency check failed: %s", e)
                inc("orchestrator_tick_errors_total", {"tick": "balance"})
            finally:
                dt = (now_ms() - t0) / 1000.0
                observe_histogram("tick_balance_seconds", dt, {"exchange": ex})
                await asyncio.sleep(self.balance_interval)

    async def _tick_watchdog(self) -> None:
        """Сторож: отслеживает «залипание» основных циклов."""
        while self._running:
            try:
                now = now_ms()
                if now - self._last_eval_ms > self.watchdog_stall_sec * 1000:
                    inc("watchdog_stall_total", {"loop": "eval"})
                if now - self._last_reconcile_ms > self.watchdog_stall_sec * 1000:
                    inc("watchdog_stall_total", {"loop": "reconcile"})
                if now - self._last_exits_ms > self.watchdog_stall_sec * 1000:
                    inc("watchdog_stall_total", {"loop": "exits"})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("watchdog failed: %s", e)
            finally:
                await asyncio.sleep(self.watchdog_interval)
