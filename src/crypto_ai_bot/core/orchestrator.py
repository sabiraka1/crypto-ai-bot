# src/crypto_ai_bot/core/orchestrator.py
"""
Orchestrator — координация фоновых циклов:
- периодическая оценка стратегии и исполнение (evaluate → place_order)
- проверка protective exits (если use-case подключён)
- reconcile pending ордеров с биржей
- heartbeat (KV), чтобы health/alerts видели «пульс»
- graceful shutdown

ВАЖНО: никаких прямых os.environ — все только через settings.
"""

from __future__ import annotations
import asyncio
from typing import Any, Optional, Callable
from datetime import datetime, timezone

from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Any,
        broker: Any,
        repositories: Any,
        event_bus: Optional[Any] = None,
        logger: Optional[Any] = None,
        # интервалы (сек) — берем из settings, но оставляем параметры для тестов
        eval_interval_sec: Optional[float] = None,
        exits_interval_sec: Optional[float] = None,
        reconcile_interval_sec: Optional[float] = None,
        heartbeat_interval_sec: Optional[float] = None,
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.repos = repositories
        self.bus = event_bus
        self.log = logger or getattr(settings, "logger", None)

        # интервалы
        s = settings
        self.eval_interval = float(eval_interval_sec or getattr(s, "EVAL_INTERVAL_SEC", 60.0))
        self.exits_interval = float(exits_interval_sec or getattr(s, "EXITS_INTERVAL_SEC", 5.0))
        self.reconcile_interval = float(reconcile_interval_sec or getattr(s, "RECONCILE_INTERVAL_SEC", 60.0))
        self.heartbeat_interval = float(heartbeat_interval_sec or getattr(s, "HEARTBEAT_INTERVAL_SEC", 15.0))

        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    # ------------------ ПУБЛИЧНЫЙ API ------------------

    async def start(self) -> None:
        """
        Запуск фоновых циклов.
        1) Одноразовый reconcile на старте — снижает шанс «дубля» после рестарта.
        2) Параллельно: evaluate, exits, reconcile, heartbeat.
        """
        if self.log:
            self.log.info("orchestrator.start: begin")

        # single-shot reconcile
        try:
            await self._reconcile_once()
        except Exception:  # не валим старт, просто логируем
            if self.log:
                self.log.exception("orchestrator.start: initial reconcile failed")

        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._tick_eval(), name="tick_eval"),
            loop.create_task(self._tick_exits(), name="tick_exits"),
            loop.create_task(self._tick_reconcile(), name="tick_reconcile"),
            loop.create_task(self._tick_heartbeat(), name="tick_heartbeat"),
        ]

        if self.log:
            self.log.info("orchestrator.start: started %d tasks", len(self._tasks))

    async def stop(self) -> None:
        """
        Корректная остановка: даём таскам выйти из своих циклов, ждём завершения.
        """
        if self.log:
            self.log.info("orchestrator.stop: stopping...")
        self._stopping.set()
        for t in self._tasks:
            t.cancel()  # «мягкая» отмена; в циклах есть проверка self._stopping
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.log:
            self.log.info("orchestrator.stop: stopped")

    # ------------------ ВНУТРЕННИЕ ЦИКЛЫ ------------------

    async def _tick_eval(self) -> None:
        """
        Основной торговый цикл: evaluate → (если ok) → place_order. Один символ из settings.
        """
        sym = getattr(self.settings, "SYMBOL", "BTC/USDT")
        cfg = self.settings
        repos = self.repos
        while not self._stopping.is_set():
            try:
                await evaluate_and_maybe_execute(
                    symbol=sym,
                    cfg=cfg,
                    broker=self.broker,
                    positions_repo=getattr(repos, "positions_repo", None),
                    trades_repo=getattr(repos, "trades_repo", None),
                    idempotency_repo=getattr(repos, "idempotency_repo", None),
                    exits_repo=getattr(repos, "exits_repo", None),
                    audit_repo=getattr(repos, "audit_repo", None),
                    market_meta_repo=getattr(repos, "market_meta_repo", None),
                    external=getattr(repos, "external", None),
                    event_bus=self.bus,
                )
            except Exception:
                if self.log:
                    self.log.exception("orchestrator.tick_eval: evaluate_and_maybe_execute failed")
            await asyncio.wait_for(self._stopping.wait(), timeout=self.eval_interval)

    async def _tick_exits(self) -> None:
        """
        Мониторинг/исполнение protective exits, если соответствующий use-case присутствует.
        """
        # допускаем разные раскладки (совместимость)
        exits_fn: Optional[Callable[..., Any]] = None
        for path in (
            "crypto_ai_bot.core.use_cases.protective_exits.run_protective_exits_check",
            "crypto_ai_bot.core.use_cases.exits.run_protective_exits_check",
        ):
            try:
                module_path, fn_name = path.rsplit(".", 1)
                mod = __import__(module_path, fromlist=[fn_name])
                exits_fn = getattr(mod, fn_name, None)
                if exits_fn:
                    break
            except Exception:
                continue

        if exits_fn is None and self.log:
            self.log.info("orchestrator.tick_exits: no exits use-case found; skipping")

        sym = getattr(self.settings, "SYMBOL", "BTC/USDT")
        repos = self.repos
        while not self._stopping.is_set():
            if exits_fn:
                try:
                    await exits_fn(
                        symbol=sym,
                        broker=self.broker,
                        exits_repo=getattr(repos, "exits_repo", None),
                        trades_repo=getattr(repos, "trades_repo", None),
                        positions_repo=getattr(repos, "positions_repo", None),
                        event_bus=self.bus,
                        settings=self.settings,
                    )
                except Exception:
                    if self.log:
                        self.log.exception("orchestrator.tick_exits: exits check failed")
            await asyncio.wait_for(self._stopping.wait(), timeout=self.exits_interval)

    async def _reconcile_once(self) -> None:
        """
        Одноразовый reconcile (на старте). Если в repo есть специальный метод — используем его.
        Иначе пытаемся «мягко» вызвать fetch_open_orders и обновить состояния через trades_repo, если он это умеет.
        """
        trades_repo = getattr(self.repos, "trades_repo", None)
        if trades_repo is None:
            return
        # Специализированный метод?
        if hasattr(trades_repo, "reconcile_pending_once"):
            try:
                await trades_repo.reconcile_pending_once(broker=self.broker)
                return
            except TypeError:
                # может быть синхронным
                try:
                    trades_repo.reconcile_pending_once(broker=self.broker)
                    return
                except Exception:
                    pass
            except Exception:
                if self.log:
                    self.log.exception("orchestrator.reconcile_once: repo.reconcile_pending_once failed")
                return

        # Универсальная «мягкая» попытка:
        try:
            open_orders = self.broker.fetch_open_orders(getattr(self.settings, "SYMBOL", "BTC/USDT"))
            if hasattr(trades_repo, "record_exchange_snapshot"):
                trades_repo.record_exchange_snapshot(open_orders)
        except Exception:
            if self.log:
                self.log.exception("orchestrator.reconcile_once: generic snapshot failed")

    async def _tick_reconcile(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._reconcile_once()
            except Exception:
                if self.log:
                    self.log.exception("orchestrator.tick_reconcile: failed")
            await asyncio.wait_for(self._stopping.wait(), timeout=self.reconcile_interval)

    async def _tick_heartbeat(self) -> None:
        """
        Записываем «пульс» в KV, если repo есть. Это очень помогает для health/alerts.
        """
        kv = getattr(self.repos, "kv_repo", None)
        key = "orchestrator_heartbeat_ms"
        while not self._stopping.is_set():
            try:
                if kv and hasattr(kv, "set"):
                    kv.set(key, str(_now_ms()))
            except Exception:
                if self.log:
                    self.log.exception("orchestrator.tick_heartbeat: kv.set failed")
            await asyncio.wait_for(self._stopping.wait(), timeout=self.heartbeat_interval)
