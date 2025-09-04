from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.bus_adapter import UnifiedEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.safety.instance_lock import InstanceLock
from crypto_ai_bot.core.infrastructure.storage.facade import StorageFacade
from crypto_ai_bot.core.infrastructure.storage.sqlite_adapter import SQLiteAdapter
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("compose")


@dataclass
class AppContainer:
    """Application dependency container."""

    settings: Any
    storage: StorageFacade
    broker: Any
    bus: UnifiedEventBus
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    dms: DeadMansSwitch
    instance_lock: InstanceLock
    orchestrators: dict[str, Orchestrator]


# ----------------------------- Bus -----------------------------
def _make_bus(settings: Any) -> UnifiedEventBus:
    """Create event bus based on settings."""
    url = getattr(settings, "EVENT_BUS_URL", "") or ""
    if url.startswith("redis://"):
        _log.info("event_bus.redis.enabled", extra={"url": url})
        base_bus = RedisEventBus(url=url)
    else:
        _log.info("event_bus.memory.enabled")
        base_bus = AsyncEventBus()

    return UnifiedEventBus(base_bus)


# ----------------------------- Storage -----------------------------
def _make_storage(settings: Any) -> StorageFacade:
    """Create storage facade."""
    path = getattr(settings, "DB_PATH", "app.db")
    _log.info("storage.sqlite", extra={"path": path})
    adapter = SQLiteAdapter(path)
    return StorageFacade(adapter)


# ----------------------------- Broker -----------------------------
def _make_broker(settings: Any) -> Any:
    """Create broker instance."""
    return make_broker(
        mode=getattr(settings, "MODE", "paper"),
        exchange=getattr(settings, "EXCHANGE", "gateio"),
        api_key=getattr(settings, "API_KEY", ""),
        secret=getattr(settings, "API_SECRET", ""),
        password=getattr(settings, "API_PASSWORD", None),
        sandbox=bool(getattr(settings, "SANDBOX", False)),
        settings=settings,
    )


# ----------------------------- Risk -----------------------------
def _make_risk(settings: Any, broker: Any) -> RiskManager:
    """Create risk manager with spread provider."""

    # Spread provider function
    async def spread_provider(symbol: str) -> float | None:
        try:
            ticker = await broker.fetch_ticker(symbol)
            bid = float(ticker.get("bid", 0))
            ask = float(ticker.get("ask", 0))
            if bid > 0 and ask > 0:
                return ((ask - bid) / ((ask + bid) / 2)) * 100
        except Exception:
            pass
        return None

    config = RiskConfig.from_settings(settings, spread_provider=spread_provider)
    return RiskManager(config)


# ----------------------------- Protective exits -----------------------------
def _make_protective_exits(
    broker: Any, storage: StorageFacade, bus: UnifiedEventBus, settings: Any
) -> ProtectiveExits:
    """Create protective exits handler."""
    return ProtectiveExits(
        broker=broker,
        storage=storage,
        bus=bus,
        settings=settings,
    )


# ----------------------------- Health -----------------------------
def _make_health(storage: StorageFacade, broker: Any, bus: UnifiedEventBus, settings: Any) -> HealthChecker:
    """Create health checker."""
    return HealthChecker(
        storage=storage,
        broker=broker,
        bus=bus,
        settings=settings,
    )


# ----------------------------- Safety -----------------------------
def _make_dms(bus: UnifiedEventBus, broker: Any, settings: Any) -> DeadMansSwitch:
    """Create dead man's switch."""
    return DeadMansSwitch(
        bus=bus,
        broker=broker,
        settings=settings,
    )


def _make_instance_lock(settings: Any) -> InstanceLock:
    """Create instance lock."""
    db_path = getattr(settings, "DB_PATH", "app.db")
    lock_path = f"{db_path}.lock"
    return InstanceLock(lock_path)


# ----------------------------- Orchestrators -----------------------------
def _create_orchestrators(
    settings: Any,
    storage: StorageFacade,
    broker: Any,
    bus: UnifiedEventBus,
    risk: RiskManager,
    exits: ProtectiveExits,
    health: HealthChecker,
    dms: DeadMansSwitch,
) -> dict[str, Orchestrator]:
    """Create orchestrators for configured symbols."""
    orchestrators = {}

    # Get symbols list
    symbols_str = getattr(settings, "SYMBOLS", "") or getattr(settings, "SYMBOL", "BTC/USDT")
    symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

    if not symbols:
        symbols = ["BTC/USDT"]

    for symbol in symbols:
        orch = Orchestrator(
            symbol=symbol,
            storage=storage,
            broker=broker,
            bus=bus,
            risk=risk,
            exits=exits,
            health=health,
            settings=settings,
            dms=dms,
        )
        orchestrators[symbol] = orch
        _log.info("orchestrator_created", extra={"symbol": symbol})

    return orchestrators


# ----------------------------- Telegram integration -----------------------------
def _setup_telegram(bus: UnifiedEventBus, settings: Any) -> None:
    """Setup Telegram integrations if enabled."""
    if not int(getattr(settings, "TELEGRAM_ENABLED", 0)):
        _log.info("telegram.disabled")
        return

    try:
        # Import here to avoid dependencies when Telegram is disabled
        from crypto_ai_bot.app.telegram_alerts import attach_alerts

        attach_alerts(bus, settings)
        _log.info("telegram.alerts.attached")

        # Setup bot commands if enabled
        if int(getattr(settings, "TELEGRAM_BOT_COMMANDS_ENABLED", 0)):
            # Bot commands would be initialized in server.py when needed
            _log.info("telegram.commands.ready")
    except ImportError:
        _log.warning("telegram_modules_not_found")
    except Exception:
        _log.error("telegram_setup_failed", exc_info=True)


# ----------------------------- Public compose functions -----------------------------
async def build_container_async() -> AppContainer:
    """Asynchronously build the application container."""
    _log.info("compose.start")

    # Load settings
    from crypto_ai_bot.core.infrastructure.settings import Settings

    settings = Settings.load()

    # Core components
    bus = _make_bus(settings)
    storage = _make_storage(settings)
    broker = _make_broker(settings)

    # Risk / Exits / Health / Safety
    risk = _make_risk(settings, broker)
    exits = _make_protective_exits(broker, storage, bus, settings)
    health = _make_health(storage, broker, bus, settings)
    dms = _make_dms(bus, broker, settings)
    instance_lock = _make_instance_lock(settings)

    # Try to acquire instance lock
    if not instance_lock.acquire():
        _log.warning("instance_lock_already_held")

    # Create orchestrators
    orchestrators = _create_orchestrators(settings, storage, broker, bus, risk, exits, health, dms)

    # Setup Telegram if enabled
    _setup_telegram(bus, settings)  # Убрали неиспользуемый аргумент storage

    # Auto-start orchestrators if configured
    if int(getattr(settings, "TRADER_AUTOSTART", 0)):
        for symbol, orch in orchestrators.items():
            try:
                await orch.start()
                _log.info("orchestrator_auto_started", extra={"symbol": symbol})
            except Exception:
                _log.error("orchestrator_auto_start_failed", extra={"symbol": symbol}, exc_info=True)

    _log.info("compose.done")

    return AppContainer(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        dms=dms,
        instance_lock=instance_lock,
        orchestrators=orchestrators,
    )


def compose() -> AppContainer:
    """Synchronously build the application container."""
    return asyncio.run(build_container_async())