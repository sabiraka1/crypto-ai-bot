from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional
from importlib import import_module
from decimal import Decimal

from ..core.settings import Settings
from ..core.events.bus import AsyncEventBus
from ..core.monitoring.health_checker import HealthChecker
from ..core.storage.facade import Storage
from ..core.storage.migrations.runner import run_migrations
from ..core.brokers.base import IBroker, TickerDTO, BalanceDTO, OrderDTO  # для фолбэк брокера
from ..core.brokers.ccxt_exchange import CCXTBroker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits
from ..core.orchestrator import Orchestrator
from ..utils.logging import get_logger
from ..utils.time import now_ms

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator


def _load_paper_broker_class():
    """
    Динамически ищем PaperBroker в самых распространённых расположениях,
    чтобы не падать, если модуль называется иначе в текущей ветке.
    """
    candidates = [
        ("..core.brokers.paper", "PaperBroker"),
        ("..core.brokers.paper_broker", "PaperBroker"),
        ("..core.brokers.simulated", "PaperBroker"),
        ("..core.brokers.backtest", "PaperBroker"),
    ]
    for mod, cls in candidates:
        try:
            m = import_module(mod, package=__package__)
            broker_cls = getattr(m, cls)
            _log.info("paper_broker_loaded", extra={"module": mod, "class": cls})
            return broker_cls
        except Exception:
            continue
    _log.info("paper_broker_not_found_using_fallback")
    return None


# Фолбэк-реализация PaperBroker (включается только если модуль не найден).
class _FallbackPaperBroker(IBroker):
    def __init__(self, storage: Storage, *, price: float = 100.0):
        self._storage = storage
        self._price = float(price)

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        p = self._price
        return TickerDTO(symbol=symbol, last=p, bid=p - 0.1, ask=p + 0.1, timestamp=now_ms())

    async def fetch_balance(self) -> BalanceDTO:
        # достаточно USDT для тестов/бэктеста; позиции учитывает storage
        return BalanceDTO(free={"USDT": 10_000.0}, total={"USDT": 10_000.0})

    async def create_market_buy_quote(self, symbol: str, quote_amount: float | Decimal, *, client_order_id: str | None = None) -> OrderDTO:
        price = self._price
        qa = float(quote_amount)
        base = qa / price if price > 0 else 0.0
        return OrderDTO(
            id=(client_order_id or f"fb-buy-{now_ms()}"),
            client_order_id=(client_order_id or ""),
            symbol=symbol,
            side="buy",
            amount=base,
            status="closed",
            filled=base,
            timestamp=now_ms(),
            price=price,
        )

    async def create_market_sell_base(self, symbol: str, base_amount: float | Decimal, *, client_order_id: str | None = None) -> OrderDTO:
        price = self._price
        ba = float(base_amount)
        return OrderDTO(
            id=(client_order_id or f"fb-sell-{now_ms()}"),
            client_order_id=(client_order_id or ""),
            symbol=symbol,
            side="sell",
            amount=ba,
            status="closed",
            filled=ba,
            timestamp=now_ms(),
            price=price,
        )


def _create_storage_for_mode(settings: Settings) -> Storage:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    run_migrations(conn)
    _log.info("migrations_applied", extra={"versions": ["0001_init"]})
    storage = Storage.from_connection(conn)
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": settings.DB_PATH, "migrations_applied": 1})
    return storage


def _create_broker_for_mode(settings: Settings, storage: Storage) -> IBroker:
    if settings.MODE == "live":
        _log.info("creating_live_broker", extra={"exchange": settings.EXCHANGE})
        return CCXTBroker(exchange_name=settings.EXCHANGE, api_key=settings.API_KEY, api_secret=settings.API_SECRET)
    else:
        # Пытаемся найти PaperBroker в проекте; иначе — фолбэк
        PaperBroker = _load_paper_broker_class()
        if PaperBroker is not None:
            _log.info("creating_paper_broker", extra={"mode": settings.MODE})
            return PaperBroker(storage=storage)
        _log.info("creating_fallback_paper_broker", extra={"mode": settings.MODE})
        return _FallbackPaperBroker(storage=storage)


def build_container() -> Container:
    """🎯 СБОРКА КОНТЕЙНЕРА С ПРАВИЛЬНЫМ ВЫБОРОМ КОМПОНЕНТОВ ПО РЕЖИМУ."""
    # 1) settings
    settings = Settings.load()
    _log.info("building_container", extra={
        "mode": settings.MODE, "exchange": settings.EXCHANGE, "symbol": settings.SYMBOL,
    })

    # 2) storage
    storage = _create_storage_for_mode(settings)

    # 3) event bus
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)

    # 4) broker
    broker = _create_broker_for_mode(settings, storage)

    # 5) risk manager (из ENV)
    risk_cfg = RiskConfig(
        cooldown_sec=settings.RISK_COOLDOWN_SEC,
        max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
        daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
        max_position_base=settings.RISK_MAX_POSITION_BASE,
        max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
    )
    risk = RiskManager(storage=storage, config=risk_cfg)

    # 6) protective exits
    exits = ProtectiveExits(storage=storage, broker=broker)

    # 7) health checker
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    # 8) orchestrator
    orch = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
    )

    _log.info("container_built", extra={"mode": settings.MODE, "components": [
        "settings", "storage", "broker", "bus", "health", "risk", "exits", "orchestrator"
    ]})
    return Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orch,
    )
