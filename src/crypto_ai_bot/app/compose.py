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
from ..core.brokers.base import IBroker, TickerDTO, BalanceDTO, OrderDTO  # Ð´Ð»Ñ Ñ„Ð¾Ð»Ð±ÑÐº Ð±Ñ€Ð¾ÐºÐµÑ€Ð°
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
    Ð"Ð¸Ð½Ð°Ð¼Ð¸Ñ‡ÐµÑÐºÐ¸ Ð¸Ñ‰ÐµÐ¼ PaperBroker Ð² ÑÐ°Ð¼Ñ‹Ñ… Ñ€Ð°ÑÐ¿Ñ€Ð¾ÑÑ‚Ñ€Ð°Ð½Ñ'Ð½Ð½Ñ‹Ñ… Ñ€Ð°ÑÐ¿Ð¾Ð»Ð¾Ð¶ÐµÐ½Ð¸ÑÑ….
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


def _load_ccxt_broker_class():
    """
    Ð›ÐµÐ½Ð¸Ð²Ð°Ñ Ð·Ð°Ð³Ñ€ÑƒÐ·ÐºÐ° CCXT Ð±Ñ€Ð¾ÐºÐµÑ€Ð°: Ð¸Ð¼Ð¿Ð¾Ñ€Ñ‚Ð¸Ñ€ÑƒÐµÐ¼ Ð¢ÐžÐ›Ð¬ÐšÐž ÐºÐ¾Ð³Ð´Ð° MODE=live.
    Ð•ÑÐ»Ð¸ ÐºÐ»Ð°ÑÑ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ â€" Ð²ÐµÑ€Ð½Ñ'Ð¼ None (Ð½Ð¸Ð¶Ðµ ÑÑ„Ð¾Ñ€Ð¼Ð¸Ñ€ÑƒÐµÐ¼ Ð¿Ð¾Ð½ÑÑ‚Ð½ÑƒÑŽ Ð¾ÑˆÐ¸Ð±ÐºÐ°).
    """
    candidates = [
        ("..core.brokers.ccxt_exchange", "CCXTBroker"),
        ("..core.brokers.ccxt", "CCXTBroker"),
    ]
    for mod, cls in candidates:
        try:
            m = import_module(mod, package=__package__)
            broker_cls = getattr(m, cls)
            _log.info("ccxt_broker_loaded", extra={"module": mod, "class": cls})
            return broker_cls
        except Exception:
            continue
    return None


# Ð¤Ð¾Ð»Ð±ÑÐº PaperBroker (Ð²ÐºÐ»ÑŽÑ‡Ð°ÐµÑ‚ÑÑ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ ÐµÑÐ»Ð¸ Ð¼Ð¾Ð´ÑƒÐ»ÑŒ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½).
class _FallbackPaperBroker(IBroker):
    def __init__(self, storage: Storage, *, price: float = 100.0):
        self._storage = storage
        self._price = float(price)

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        p = Decimal(str(self._price))  # ✅ Конвертируем в Decimal
        return TickerDTO(symbol=symbol, last=p, bid=p - Decimal("0.1"), ask=p + Decimal("0.1"), timestamp=now_ms())

    async def fetch_balance(self) -> BalanceDTO:
        free_bal = {"USDT": Decimal("10000.0")}
        total_bal = {"USDT": Decimal("10000.0")}
        used_bal = {"USDT": Decimal("0.0")}
        return BalanceDTO(free=free_bal, used=used_bal, total=total_bal, timestamp=now_ms())

    async def create_market_buy_quote(self, symbol: str, quote_amount: float | Decimal, *, client_order_id: str | None = None) -> OrderDTO:
        price = Decimal(str(self._price))  # ✅ Конвертируем в Decimal
        qa = Decimal(str(quote_amount))
        base = qa / price if price > 0 else Decimal("0")
        return OrderDTO(
            id=(client_order_id or f"fb-buy-{now_ms()}"),
            client_order_id=(client_order_id or ""),
            symbol=symbol,
            side="buy",
            amount=base,
            cost=qa,  # ✅ cost = quote_amount для buy
            status="closed",
            filled=base,
            timestamp=now_ms(),
            price=price,
        )

    async def create_market_sell_base(self, symbol: str, base_amount: float | Decimal, *, client_order_id: str | None = None) -> OrderDTO:
        price = Decimal(str(self._price))  # ✅ Конвертируем в Decimal
        ba = Decimal(str(base_amount))
        cost = ba * price  # cost = base_amount * price для sell
        return OrderDTO(
            id=(client_order_id or f"fb-sell-{now_ms()}"),
            client_order_id=(client_order_id or ""),
            symbol=symbol,
            side="sell",
            amount=ba,
            cost=cost,
            status="closed",
            filled=ba,
            timestamp=now_ms(),
            price=price,
        )


def _create_storage_for_mode(settings: Settings) -> Storage:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    run_migrations(conn, now_ms=now_ms())  # ✅ Добавлен параметр now_ms
    _log.info("migrations_applied", extra={"versions": ["0001_init"]})
    storage = Storage.from_connection(conn)
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": settings.DB_PATH, "migrations_applied": 1})
    return storage


def _create_broker_for_mode(settings: Settings, storage: Storage) -> IBroker:
    if settings.MODE == "live":
        _log.info("creating_live_broker", extra={"exchange": settings.EXCHANGE})
        CCXTBroker = _load_ccxt_broker_class()
        if CCXTBroker is None:
            raise ImportError(
                "CCXTBroker not found. Make sure core/brokers/ccxt_exchange.py defines CCXTBroker "
                "Ð¸Ð»Ð¸ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐ¹Ñ‚Ðµ MODE=paper Ð´Ð»Ñ Ð»Ð¾ÐºÐ°Ð»ÑŒÐ½Ñ‹Ñ… Ñ‚ÐµÑÑ‚Ð¾Ð²."
            )
        return CCXTBroker(exchange_name=settings.EXCHANGE, api_key=settings.API_KEY, api_secret=settings.API_SECRET)
    else:
        PaperBroker = _load_paper_broker_class()
        if PaperBroker is not None:
            _log.info("creating_paper_broker", extra={"mode": settings.MODE})
            return PaperBroker(storage=storage)
        _log.info("creating_fallback_paper_broker", extra={"mode": settings.MODE})
        return _FallbackPaperBroker(storage=storage)


def build_container() -> Container:
    """ðŸŽ¯ Ð¡Ð'ÐžÐ ÐšÐ ÐšÐžÐÐ¢Ð•Ð™ÐÐ•Ð Ð Ð¡ ÐŸÐ ÐÐ'Ð˜Ð›Ð¬ÐÐ«Ðœ Ð'Ð«Ð'ÐžÐ ÐžÐœ ÐšÐžÐœÐŸÐžÐÐ•ÐÐ¢ÐžÐ' ÐŸÐž Ð Ð•Ð–Ð˜ÐœÐ£."""
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

    # 5) risk manager (Ð¸Ð· ENV)
    risk_cfg = RiskConfig(
        cooldown_sec=settings.RISK_COOLDOWN_SEC,
        max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
        daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
        max_position_base=settings.RISK_MAX_POSITION_BASE,
        max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
    )
    risk = RiskManager(storage=storage, config=risk_cfg)

    # 6) protective exits
    exits = ProtectiveExits(storage=storage, policy=None, bus=bus)

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