# src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class Orchestrator:
    settings: Any
    broker: Any
    repos: Any
    bus: Any

    _tasks: list[asyncio.Task] = field(default_factory=list, init=False)
    _running: bool = field(default=False, init=False)

    # простой TTL-кеш для тикеров (не выносил в отдельные файлы)
    _ticker_cache: Dict[str, Tuple[float, dict]] = field(default_factory=dict, init=False)
    _ticker_ttl_sec: float = 3.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._tasks = [
            asyncio.create_task(self._tick_eval(), name="tick_eval"),
            asyncio.create_task(self._tick_exits(), name="tick_exits"),
            asyncio.create_task(self._tick_reconcile(), name="tick_reconcile"),
            asyncio.create_task(self._tick_watchdog(), name="tick_watchdog"),
        ]
        logger.info("orchestrator started", extra={"tasks": [t.get_name() for t in self._tasks]})

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("orchestrator stopped")

    # ---------- helpers ----------

    def _get_ticker_cached(self, symbol: str) -> dict | None:
        now = time.time()
        hit = self._ticker_cache.get(symbol)
        if hit and (now - hit[0]) < self._ticker_ttl_sec:
            return hit[1]
        try:
            tk = self.broker.fetch_ticker(symbol)
            self._ticker_cache[symbol] = (now, tk or {})
            return tk
        except Exception:
            logger.exception("fetch_ticker failed")
            return None

    # ---------- ticks ----------

    async def _tick_eval(self) -> None:
        interval = getattr(self.settings, "EVAL_INTERVAL_SEC", 60)
        while self._running:
            try:
                from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute
                sym = getattr(self.settings, "SYMBOL", "BTC/USDT")

                await evaluate_and_maybe_execute(
                    symbol=sym,
                    settings=self.settings,
                    broker=self.broker,
                    repos=self.repos,
                    bus=self.bus,
                    external=True,  # safe-mode eval
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("evaluate_and_maybe_execute failed")
            finally:
                await asyncio.sleep(interval)

    async def _tick_exits(self) -> None:
        interval = getattr(self.settings, "EXITS_INTERVAL_SEC", 5)
        sym = getattr(self.settings, "SYMBOL", "BTC/USDT")
        while self._running:
            try:
                # используем кеш тикера, чтобы не долбить API
                ticker = self._get_ticker_cached(sym)
                last = (ticker or {}).get("last")
                from crypto_ai_bot.core.use_cases.protective_exits import run_protective_exits_check

                await run_protective_exits_check(
                    symbol=sym,
                    last_price=last,
                    settings=self.settings,
                    broker=self.broker,
                    repos=self.repos,
                    bus=self.bus,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("protective_exits tick failed")
            finally:
                await asyncio.sleep(interval)

    async def _tick_reconcile(self) -> None:
        interval = getattr(self.settings, "RECONCILE_INTERVAL_SEC", 60)
        while self._running:
            try:
                from crypto_ai_bot.core.use_cases.reconcile import reconcile_once
                await reconcile_once(self.settings, self.broker, self.repos, self.bus)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reconcile tick failed")
            finally:
                await asyncio.sleep(interval)

    async def _tick_watchdog(self) -> None:
        interval = getattr(self.settings, "WATCHDOG_INTERVAL_SEC", 15)
        while self._running:
            try:
                # здесь можно снимать метрики длины очереди, стейта брейкера и т.п.
                pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watchdog tick failed")
            finally:
                await asyncio.sleep(interval)
