## `compose.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Callable
import contextlib
from ..core.settings import Settings
from ..core.events.bus import AsyncEventBus
from ..core.brokers.backtest_exchange import BacktestExchange
from ..core.brokers.ccxt_exchange import CcxtExchange
from ..core.storage.sqlite_adapter import connect
from ..core.storage.migrations.runner import run_migrations
from ..core.storage.facade import Storage
from ..core.monitoring.health_checker import HealthChecker
from ..core.risk.manager import RiskManager, RiskConfig
from ..core.risk.protective_exits import ProtectiveExits, ExitPolicy
@dataclass(frozen=True)
class Container:
    settings: Settings
    storage: Storage
    broker: object  # IBroker
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
def _mk_price_feed(storage: Storage, default: Decimal = Decimal("50000")) -> Callable[[], Decimal]:
    from ..core.storage.repositories.market_data import TickerRow  # local import to avoid cycles
    def feed() -> Decimal:
        row = storage.market_data.get_last_ticker("BTC/USDT")
        if row and row.last > 0:
            return row.last
        return default
    return feed
def build_container() -> Container:
    settings = Settings.load()
    conn = connect(settings.DB_PATH)
    run_migrations(conn, now_ms=0)
    storage = Storage.from_connection(conn)
    bus = AsyncEventBus()
    if settings.MODE == "live":
        broker = CcxtExchange(exchange=settings.EXCHANGE, api_key=settings.API_KEY, api_secret=settings.API_SECRET)
    else:
        broker = BacktestExchange(symbol=settings.SYMBOL, balances={"USDT": Decimal("10000")}, price_feed=_mk_price_feed(storage))
    risk = RiskManager(storage=storage, bus=bus, config=RiskConfig())
    exits = ProtectiveExits(storage=storage, bus=bus, policy=ExitPolicy())
    health = HealthChecker(storage=storage, broker=broker, bus=bus)
    return Container(settings=settings, storage=storage, broker=broker, bus=bus, health=health, risk=risk, exits=exits)
@contextlib.asynccontextmanager
async def lifespan(app):
    container = build_container()
    app.state.container = container
    try:
        yield
    finally:
        try:
            if hasattr(container.broker, "close"):
                close = getattr(container.broker, "close")
                if callable(close):
                    res = close()
                    if getattr(res, "__await__", None):
                        await res  # async close
        except Exception:
            pass
        try:
            await container.bus.close()
        except Exception:
            pass
        try:
            container.storage.conn.close()
        except Exception:
            pass