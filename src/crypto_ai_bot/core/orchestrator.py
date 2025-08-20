# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute
from crypto_ai_bot.core.use_cases.reconcile import reconcile_open_orders
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, gauge
from crypto_ai_bot.utils.time import now_ms

logger = get_logger(__name__)


class Orchestrator:
    """
    Жизненный цикл бота:
      - периодический eval/execute
      - защитные выходы (heartbeat; при наличии — вызов use-case)
      - reconcile открытых ордеров
      - баланс/latency
      - watchdog/heartbeat
    """

    def __init__(
        self,
        *,
        settings: Any,
        broker: Any,
        bus: Any,
        trades_repo: Any,
        positions_repo: Any,
        exits_repo: Any,
        idempotency_repo: Any,
        limiter: Optional[Any] = None,
        audit_repo: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.bus = bus

        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.exits_repo = exits_repo
        self.idempotency_repo = idempotency_repo
        self.limiter = limiter
        self.audit_repo = audit_repo

        self._stop = asyncio.Event()
        self._tasks: Set[asyncio.Task] = set()

        # health
        self._hb_ms: int = now_ms()
        self._last_eval_ms: Optional[int] = None
        self._last_exits_ms: Optional[int] = None
        self._last_reconcile_ms: Optional[int] = None
        self._last_balance_ms: Optional[int] = None
        self._last_latency_ms: Optional[int] = None

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
        self._tasks.add(asyncio.create_task(self._tick_eval(), name="tick_eval"))
        self._tasks.add(asyncio.create_task(self._tick_exits(), name="tick_exits"))
        self._tasks.add(asyncio.create_task(self._tick_reconcile(), name="tick_reconcile"))
        self._tasks.add(asyncio.create_task(self._tick_balance_and_latency(), name="tick_balance"))
        self._tasks.add(asyncio.create_task(self._tick_watchdog(), name="tick_watchdog"))
        logger.info("orchestrator started", extra={"tasks": [t.get_name() for t in self._tasks]})

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("orchestrator stop timed out; cancelling tasks")
            for t in self._tasks:
                t.cancel()
                try:
                    await t
                except Exception:
                    pass
        finally:
            self._tasks.clear()
            logger.info("orchestrator stopped")

    # ----------------- ticks -----------------

    async def _tick_eval(self) -> None:
        interval = float(getattr(self.settings, "EVAL_INTERVAL_SEC", 60.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            started = now_ms()
            try:
                res = await evaluate_and_maybe_execute(
                    cfg=self.settings,
                    broker=self.broker,
                    positions_repo=self.positions_repo,
                    idempotency_repo=self.idempotency_repo,
                    limiter=self.limiter,
                    symbol=symbol,
                    external=None,
                )
                inc("tick_eval_success_total", {"symbol": symbol})
                logger.debug("tick_eval ok", extra={"symbol": symbol, "result": str(res)[:300]})
            except Exception as e:
                inc("tick_eval_errors_total", {"symbol": symbol})
                logger.error("tick_eval failed", extra={"symbol": symbol, "error": str(e)})
            finally:
                self._last_eval_ms = now_ms()
                self._hb_ms = self._last_eval_ms
                elapsed = max(0.0, (self._last_eval_ms - started) / 1000.0)
                sleep_for = max(0.0, interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

    async def _tick_exits(self) -> None:
        interval = float(getattr(self.settings, "EXITS_INTERVAL_SEC", 5.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            try:
                # Здесь можно вызвать ваш use-case защитных выходов, если он есть.
                inc("tick_exits_heartbeat_total", {"symbol": symbol})
            except Exception as e:
                inc("tick_exits_errors_total", {"symbol": symbol})
                logger.error("tick_exits failed", extra={"symbol": symbol, "error": str(e)})
            finally:
                self._last_exits_ms = now_ms()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_reconcile(self) -> None:
        interval = float(getattr(self.settings, "RECONCILE_INTERVAL_SEC", 60.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            try:
                res = await reconcile_open_orders(
                    broker=self.broker, trades_repo=self.trades_repo, symbol=symbol
                )
                logger.debug("reconcile result", extra={"symbol": symbol, "result": str(res)[:300]})
                inc("tick_reconcile_success_total", {"symbol": symbol})
            except Exception as e:
                inc("tick_reconcile_errors_total", {"symbol": symbol})
                logger.error("tick_reconcile failed", extra={"symbol": symbol, "error": str(e)})
            finally:
                self._last_reconcile_ms = now_ms()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_balance_and_latency(self) -> None:
        interval = float(getattr(self.settings, "BALANCE_INTERVAL_SEC", 300.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            t0 = now_ms()
            try:
                # неблокирующий вызов синхронного CCXT
                ticker = await asyncio.to_thread(self.broker.fetch_ticker, symbol)
                _ = ticker.get("last", None)
                self._last_latency_ms = now_ms() - t0
                gauge("exchange_last_latency_ms", float(self._last_latency_ms or 0.0), {"symbol": symbol})
                inc("tick_balance_heartbeat_total", {"symbol": symbol})
            except Exception as e:
                inc("tick_balance_errors_total", {"symbol": symbol})
                logger.error("tick_balance failed", extra={"symbol": symbol, "error": str(e)})
            finally:
                self._last_balance_ms = now_ms()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick_watchdog(self) -> None:
        interval = float(getattr(self.settings, "WATCHDOG_INTERVAL_SEC", 10.0))
        symbol = normalize_symbol(getattr(self.settings, "SYMBOL", "BTC/USDT"))
        while not self._stop.is_set():
            try:
                self._hb_ms = now_ms()
                gauge("orchestrator_heartbeat_ms", float(self._hb_ms), {"symbol": symbol})
            except Exception as e:
                logger.warning("watchdog tick failed", extra={"symbol": symbol, "error": str(e)})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
