from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Callable
import contextlib
import os

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
from ..core.orchestrator import Orchestrator
from ..utils.logging import get_logger
from ..utils.time import now_ms

_log = get_logger("compose")

@dataclass(frozen=True)
class Container:
    """🎯 DI Container с поддержкой режимов по спецификации."""
    settings: Settings
    storage: Storage
    broker: object  # IBroker
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator


def _mk_price_feed(storage: Storage, default: Decimal = Decimal("50000")) -> Callable[[], Decimal]:
    """Создаем price feed для BacktestExchange из данных в storage."""
    from ..core.storage.repositories.market_data import TickerRow  # local import to avoid cycles
    
    def feed() -> Decimal:
        row = storage.market_data.get_last_ticker("BTC/USDT")
        if row and row.last > 0:
            return row.last
        return default
    return feed


def _create_broker_for_mode(settings: Settings, storage: Storage) -> object:
    """🎯 СОЗДАНИЕ ПРАВИЛЬНОГО БРОКЕРА С ИСПРАВЛЕННЫМИ АРГУМЕНТАМИ."""
    
    if settings.MODE == "live":
        # 🔴 LIVE MODE - CcxtExchange с правильными аргументами
        if not settings.API_KEY or not settings.API_SECRET:
            raise ValueError("Live mode requires API_KEY and API_SECRET")
        
        _log.info("creating_live_broker", extra={
            "exchange": settings.EXCHANGE,
            "has_api_key": bool(settings.API_KEY),
            "has_api_secret": bool(settings.API_SECRET),
        })
        
        # ✅ ИСПРАВЛЕННЫЕ АРГУМЕНТЫ для CcxtExchange:
        return CcxtExchange(
            exchange=settings.EXCHANGE,           # ✅ правильно
            api_key=settings.API_KEY,            # ✅ правильно
            api_secret=settings.API_SECRET,      # ✅ правильно
            enable_rate_limit=True,              # ✅ правильно
            timeout_ms=20_000,                   # ✅ правильно
        )
    
    else:  # paper, backtest или любой другой режим
        # 🟢 PAPER/BACKTEST MODE - BacktestExchange с правильными аргументами
        
        # Получаем начальные балансы из настроек (с fallback на старые)
        initial_balances = {
            "USDT": getattr(settings, "PAPER_INITIAL_BALANCE_USDT", Decimal("10000")),
            "BTC": getattr(settings, "PAPER_INITIAL_BALANCE_BTC", Decimal("0")),
        }
        
        # Если нет новых настроек, используем старые значения
        if not hasattr(settings, "PAPER_INITIAL_BALANCE_USDT"):
            initial_balances = {"USDT": Decimal("10000")}
        
        _log.info("creating_paper_broker", extra={
            "mode": settings.MODE,
            "balances": {k: str(v) for k, v in initial_balances.items()},
        })
        
        # ✅ ИСПРАВЛЕННЫЕ АРГУМЕНТЫ для BacktestExchange:
        return BacktestExchange(
            symbol=settings.SYMBOL,                    # ✅ правильно
            balances=initial_balances,                 # ✅ правильно (Dict[str, Decimal])
            fee_rate=Decimal("0.001"),                 # ✅ 0.1% комиссия по умолчанию
            spread=Decimal("0.0002"),                  # ✅ 0.02% спред по умолчанию  
            price_feed=_mk_price_feed(storage),        # ✅ правильно (Optional[Callable[[], Decimal]])
        )


def _create_storage_for_mode(settings: Settings) -> Storage:
    """🎯 СОЗДАНИЕ STORAGE С ПРАВИЛЬНЫМИ ТАБЛИЦАМИ ПО РЕЖИМУ."""
    
    # Создаем директорию для БД если не существует
    db_path = settings.DB_PATH
    db_dir = os.path.dirname(db_path)
    
    if db_dir and db_dir != '.' and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        _log.info("created_db_directory", extra={"path": db_dir})
    
    # Подключаемся к БД
    conn = connect(db_path)
    
    # Запускаем миграции
    applied = run_migrations(conn, now_ms=now_ms())
    if applied:
        _log.info("migrations_applied", extra={"versions": applied})
    
    # Создаем Storage facade
    storage = Storage.from_connection(conn)
    
    _log.info("storage_created", extra={
        "mode": settings.MODE,
        "db_path": db_path,
        "migrations_applied": len(applied),
    })
    
    return storage


def build_container() -> Container:
    """🎯 СБОРКА КОНТЕЙНЕРА С ПРАВИЛЬНЫМ ВЫБОРОМ КОМПОНЕНТОВ ПО РЕЖИМУ."""
    
    # 1. Загружаем настройки
    settings = Settings.load()
    
    _log.info("building_container", extra={
        "mode": settings.MODE,
        "exchange": settings.EXCHANGE,
        "symbol": settings.SYMBOL,
    })
    
    # 2. Создаем storage
    storage = _create_storage_for_mode(settings)
    
    # 3. Создаем event bus
    bus = AsyncEventBus(
        max_attempts=3,
        backoff_base_ms=250,
        backoff_factor=2.0,
    )
    
    # 4. Создаем broker для режима
    broker = _create_broker_for_mode(settings, storage)
    
    # 5. Создаем risk manager
    risk_config = RiskConfig(
        cooldown_sec=30,
        max_spread_pct=0.3,
    )
    risk = RiskManager(storage=storage, config=risk_config)  # ✅ исправлен порядок аргументов
    
    # 6. Создаем protective exits
    exit_policy = ExitPolicy(
        take_profit_pct=2.0,  # +2%
        stop_loss_pct=1.5,    # -1.5%
    )
    exits = ProtectiveExits(storage=storage, policy=exit_policy, bus=bus)  # ✅ исправлен порядок аргументов
    
    # 7. Создаем health checker
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    # 8. Создаём orchestrator (добавлено)
    orchestrator = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
        # базовые интервалы
        eval_interval_sec=1.0,
        exits_interval_sec=2.0,
        reconcile_interval_sec=5.0,
        watchdog_interval_sec=2.0,
    )
    
    # 9. Собираем финальный контейнер
    container = Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orchestrator,
    )
    
    _log.info("container_built", extra={
        "mode": settings.MODE,
        "components": ["settings", "storage", "broker", "bus", "health", "risk", "exits", "orchestrator"],
    })
    
    return container


@contextlib.asynccontextmanager
async def lifespan(app):
    """🎯 LIFECYCLE MANAGER С ПРАВИЛЬНЫМ ЗАКРЫТИЕМ ПО РЕЖИМАМ."""
    
    container = build_container()
    app.state.container = container
    
    _log.info("lifespan_started", extra={"mode": container.settings.MODE})
    
    try:
        # Стартуем event bus явно (опционально)
        await container.bus.start()
        
        yield
        
    finally:
        _log.info("lifespan_stopping", extra={"mode": container.settings.MODE})
        
        # 1. Закрываем broker
        try:
            if hasattr(container.broker, "close"):
                close_method = getattr(container.broker, "close")
                if callable(close_method):
                    result = close_method()
                    # Проверяем если это async метод
                    if hasattr(result, "__await__"):
                        await result
                    _log.info("broker_closed")
        except Exception as exc:
            _log.error("broker_close_error", extra={"error": str(exc)})
        
        # 2. Закрываем event bus
        try:
            await container.bus.close()
            _log.info("event_bus_closed")
        except Exception as exc:
            _log.error("event_bus_close_error", extra={"error": str(exc)})
        
        # 3. Закрываем соединение с БД
        try:
            container.storage.conn.close()
            _log.info("storage_closed")
        except Exception as exc:
            _log.error("storage_close_error", extra={"error": str(exc)})
        
        _log.info("lifespan_stopped")


# 🎯 УДОБНЫЕ ФУНКЦИИ ДЛЯ ТЕСТИРОВАНИЯ

def build_test_container(*, mode: str = "paper", symbol: str = "BTC/USDT") -> Container:
    """Создать тестовый контейнер с in-memory БД."""
    import tempfile
    
    # Переопределяем настройки для тестов
    os.environ.update({
        "MODE": mode,
        "SYMBOL": symbol,
        "DB_PATH": f"{tempfile.gettempdir()}/test_crypto_bot.db",
    })
    
    return build_container()


def build_live_container_with_credentials(api_key: str, api_secret: str) -> Container:
    """Создать live контейнер с переданными креденшиалами."""
    os.environ.update({
        "MODE": "live",
        "API_KEY": api_key,
        "API_SECRET": api_secret,
    })
    
    return build_container()
