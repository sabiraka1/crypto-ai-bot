from __future__ import annotations

"""
DI-компоновка: settings → storage → broker → bus.
Без внешних зависимостей. Аккуратно работает даже если БД/репозитории/ccxt-адаптер отсутствуют.
"""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Awaitable

from crypto_ai_bot.core.settings import Settings

logger = logging.getLogger(__name__)


# -------------------- Мини-шина событий (без отдельного файла) --------------------

Handler = Callable[[str, dict], Awaitable[None]]

class AsyncEventBus:
    def __init__(self, max_queue: int = 2048, concurrency: int = 2) -> None:
        self._q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=max_queue)
        self._subs: Dict[str, List[Handler]] = {}
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._concurrency = concurrency

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, payload: dict) -> None:
        await self._q.put((topic, payload))

    def qsize(self) -> int:
        return self._q.qsize()

    async def _worker(self) -> None:
        while self._running:
            try:
                topic, payload = await self._q.get()
                for h in self._subs.get(topic, []):
                    try:
                        await h(topic, payload)
                    except Exception:
                        logger.exception("bus_handler_failed topic=%s", topic)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("bus_worker_failed")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._workers = [asyncio.create_task(self._worker(), name=f"bus-{i}") for i in range(self._concurrency)]

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()


# --------------------------------- Контейнер ---------------------------------

@dataclass
class Container:
    settings: Settings
    con: Optional[sqlite3.Connection]
    # repos (если нет — None, не ломаемся)
    trades_repo: Any | None
    positions_repo: Any | None
    exits_repo: Any | None
    idempotency_repo: Any | None
    market_data_repo: Any | None
    audit_repo: Any | None

    broker: Any
    bus: AsyncEventBus


def _build_db(settings: Settings) -> Optional[sqlite3.Connection]:
    """
    Пытаемся инициализировать SQLite.
    Если нет пути/желания — возвращаем None, ядро продолжит работать без БД.
    """
    try:
        if not settings.DB_PATH:
            return None
        con = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con
    except Exception:
        logger.exception("db_init_failed")
        return None


def _build_repos(con: Optional[sqlite3.Connection]) -> dict:
    """
    Пытаемся импортировать репозитории; если их нет — возвращаем None-ссылки.
    """
    repos: dict = {
        "trades_repo": None,
        "positions_repo": None,
        "exits_repo": None,
        "idempotency_repo": None,
        "market_data_repo": None,
        "audit_repo": None,
    }
    if not con:
        return repos

    def _safe_import(path: str, cls: str):
        mod = __import__(path, fromlist=[cls])
        return getattr(mod, cls)

    try:
        TradesRepo = _safe_import("crypto_ai_bot.core.storage.repositories.trades", "TradesRepository")
        repos["trades_repo"] = TradesRepo(con)
    except Exception:
        pass
    try:
        PositionsRepo = _safe_import("crypto_ai_bot.core.storage.repositories.positions", "PositionsRepository")
        repos["positions_repo"] = PositionsRepo(con)
    except Exception:
        pass
    try:
        ExitsRepo = _safe_import("crypto_ai_bot.core.storage.repositories.exits", "ExitsRepository")
        repos["exits_repo"] = ExitsRepo(con)
    except Exception:
        pass
    try:
        IdempRepo = _safe_import("crypto_ai_bot.core.storage.repositories.idempotency", "IdempotencyRepository")
        repos["idempotency_repo"] = IdempRepo(con)
    except Exception:
        pass
    try:
        MarketDataRepo = _safe_import("crypto_ai_bot.core.storage.repositories.market_data", "MarketDataRepository")
        repos["market_data_repo"] = MarketDataRepo(con)
    except Exception:
        pass
    try:
        AuditRepo = _safe_import("crypto_ai_bot.core.storage.repositories.audit", "AuditRepository")
        repos["audit_repo"] = AuditRepo(con)
    except Exception:
        pass

    return repos


def _build_broker(settings: Settings) -> Any:
    """
    Предпочитаем реальный адаптер, но если его нет — DummyBroker (минимально рабочий).
    """
    try:
        from crypto_ai_bot.core.brokers.ccxt_exchange import CCXTBroker  # Ваш адаптер, если есть
        return CCXTBroker(
            exchange=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
        )
    except Exception:
        # Фоллбэк: минимальный заглушечный брокер
        class _DummyBroker:
            name = "dummy"

            async def fetch_ticker(self, symbol: str) -> dict:
                return {"symbol": symbol, "last": 100.0, "bid": 99.9, "ask": 100.1, "timestamp": 0}

            async def fetch_open_orders(self, symbol: str) -> list[dict]:
                return []

            async def fetch_balance(self) -> dict:
                return {"USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}}

            async def create_order(self, symbol: str, side: str, type: str, amount: float,
                                   price: float | None = None, client_order_id: str | None = None) -> dict:
                return {
                    "id": f"dummy-{side}-{amount}",
                    "client_order_id": client_order_id or "",
                    "symbol": symbol,
                    "side": side,
                    "type": type,
                    "price": price or 0.0,
                    "amount": amount,
                    "filled": 0.0,
                    "status": "open",
                    "timestamp": 0,
                    "info": {},
                }

            async def cancel_order(self, order_id: str, symbol: str) -> None:
                return None

        return _DummyBroker()


def build_container() -> Container:
    settings = Settings.from_env()
    errors = settings.validate()
    if errors:
        # Логируем, но не падаем — запуск возможен в "degraded" режиме
        for e in errors:
            logger.warning("settings_validation: %s", e)

    con = _build_db(settings)
    repos = _build_repos(con)
    broker = _build_broker(settings)
    bus = AsyncEventBus()

    return Container(
        settings=settings,
        con=con,
        trades_repo=repos["trades_repo"],
        positions_repo=repos["positions_repo"],
        exits_repo=repos["exits_repo"],
        idempotency_repo=repos["idempotency_repo"],
        market_data_repo=repos["market_data_repo"],
        audit_repo=repos["audit_repo"],
        broker=broker,
        bus=bus,
    )
