# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Set, Callable

from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.utils.metrics import inc, gauge

# evaluate: оставляем как мягкую зависимость — если в проекте есть
# evaluate_and_maybe_execute, используем; если нет — просто публикуем тик-событие
try:
    from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute  # type: ignore
except Exception:  # pragma: no cover
    evaluate_and_maybe_execute = None  # type: ignore


class Orchestrator:
    """
    Единая точка жизненного цикла. Без блокировок event-loop.
    Интервалы берём из settings, с безопасными дефолтами.
    """

    def __init__(self, *, settings: Any, broker: Any, repos: Any, bus: Any):
        self.settings = settings
        self.broker = broker
        self.repos = repos
        self.bus = bus

        self._stop = asyncio.Event()
        self._tasks: Set[asyncio.Task] = set()

    # ---------- public API ----------

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()

        self._tasks.add(asyncio.create_task(self._guard(self._tick_eval, "tick_eval")))
        self._tasks.add(asyncio.create_task(self._guard(self._tick_exits, "tick_exits")))
        self._tasks.add(asyncio.create_task(self._guard(self._tick_reconcile, "tick_reconcile")))
        self._tasks.add(asyncio.create_task(self._guard(self._tick_balance_latency, "tick_balance_latency")))
        self._tasks.add(asyncio.create_task(self._guard(self._tick_bus_dlq, "tick_bus_dlq")))
        self._tasks.add(asyncio.create_task(self._guard(self._tick_watchdog, "tick_watchdog")))

    async def stop(self) -> None:
        self._stop.set()
        # ждём завершения всех периодических задач
        while self._tasks:
            t = self._tasks.pop()
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    # ---------- internals ----------

    async def _guard(self, coro_func: Callable[[], "asyncio.Future[Any]"], name: str) -> None:
        try:
            await coro_func()
        except asyncio.CancelledError:
            pass
        except Exception:
            # не роняем цикл из-за исключений
            inc("orchestrator_task_errors_total", {"task": name})

    async def _tick_eval(self) -> None:
        interval = float(getattr(self.settings, "EVAL_INTERVAL_SEC", 60.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            t0 = time.time()
            try:
                # если есть evaluate_and_maybe_execute — используем
                if evaluate_and_maybe_execute:
                    await asyncio.to_thread(
                        evaluate_and_maybe_execute,  # type: ignore
                        cfg=self.settings,
                        broker=self.broker,
                        repos=self.repos,
                        bus=self.bus,
                        symbol=symbol,
                    )
                else:
                    # fallback: просто публикуем «тик оценки»
                    if hasattr(self.bus, "publish"):
                        await self.bus.publish({"type": "EvalTick", "symbol": symbol, "ts_ms": int(time.time() * 1000)})
                inc("eval_ticks_total", {"symbol": symbol})
            except Exception:
                inc("eval_errors_total", {"symbol": symbol})
            # интервал
            dt = time.time() - t0
            gauge("eval_tick_seconds", dt, {"symbol": symbol})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_exits(self) -> None:
        interval = float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        # переносим бизнес-логику на use-case, если он есть
        run_exits = getattr(self.repos, "run_protective_exits_check", None)
        while not self._stop.is_set():
            try:
                if callable(run_exits):
                    await asyncio.to_thread(run_exits, symbol)  # не блокируем loop
                else:
                    # мягкий fallback: публикуем событие для внешнего обработчика
                    if hasattr(self.bus, "publish"):
                        await self.bus.publish({"type": "ProtectiveExitsTick", "symbol": symbol})
                inc("exits_ticks_total", {"symbol": symbol})
            except Exception:
                inc("exits_errors_total", {"symbol": symbol})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_reconcile(self) -> None:
        interval = float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 60.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        reconcile = getattr(self.repos, "reconcile_pending_orders", None)
        while not self._stop.is_set():
            try:
                if callable(reconcile):
                    await asyncio.to_thread(reconcile, self.broker, symbol)
                else:
                    if hasattr(self.bus, "publish"):
                        await self.bus.publish({"type": "ReconcileTick", "symbol": symbol})
                inc("reconcile_ticks_total", {"symbol": symbol})
            except Exception:
                inc("reconcile_errors_total", {"symbol": symbol})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_balance_latency(self) -> None:
        interval = float(getattr(self.settings, "BALANCE_INTERVAL_SEC", 300.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            t0 = time.time()
            try:
                # не блокируем loop при запросе к бирже
                ticker = await asyncio.to_thread(self.broker.fetch_ticker, symbol)
                latency = float(ticker.get("info", {}).get("elapsed", 0.0)) if isinstance(ticker, dict) else 0.0
                gauge("exchange_last_latency_ms", latency, {"symbol": symbol})
                inc("balance_ticks_total", {"symbol": symbol})
            except Exception:
                inc("balance_errors_total", {"symbol": symbol})
            dt = time.time() - t0
            gauge("balance_tick_seconds", dt, {"symbol": symbol})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_watchdog(self) -> None:
        interval = float(getattr(self.settings, "WATCHDOG_INTERVAL_SEC", 10.0))
        while not self._stop.is_set():
            try:
                gauge("watchdog_alive", 1)
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
                inc("bus_dlq_retry_total")
            except Exception:
                inc("bus_dlq_retry_errors_total")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
