from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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


class ComponentFactory:
    """Factory for creating application components."""

    @staticmethod
    def create_bus(settings: Any) -> UnifiedEventBus:
        """Create event bus based on settings."""
        url = getattr(settings, "EVENT_BUS_URL", "") or ""

        if url.startswith("redis://"):
            _log.info("event_bus.redis.enabled", extra={"url": url})
            base_bus = RedisEventBus(url=url)
        else:
            _log.info("event_bus.memory.enabled")
            base_bus = AsyncEventBus()

        return UnifiedEventBus(base_bus)

    @staticmethod
    def create_storage(settings: Any) -> StorageFacade:
        """Create storage facade."""
        path = getattr(settings, "DB_PATH", "app.db")
        _log.info("storage.sqlite", extra={"path": path})
        adapter = SQLiteAdapter(path)
        return StorageFacade(adapter)

    @staticmethod
    def create_broker(settings: Any) -> Any:
        """Create broker instance."""
        broker = make_broker(
            mode=getattr(settings, "MODE", "paper"),
            exchange=getattr(settings, "EXCHANGE", "gateio"),
            api_key=getattr(settings, "API_KEY", ""),
            secret=getattr(settings, "API_SECRET", ""),
            password=getattr(settings, "API_PASSWORD", None),
            sandbox=bool(getattr(settings, "SANDBOX", False)),
            settings=settings,
        )
        return broker

    @staticmethod
    async def create_spread_provider(broker: Any) -> Callable[[str], Awaitable[float | None]]:
        """Create spread provider function."""

        async def spread_provider(symbol: str) -> float | None:
            try:
                ticker = await broker.fetch_ticker(symbol)
                bid = float(ticker.get("bid", 0))
                ask = float(ticker.get("ask", 0))

                if bid > 0 and ask > 0:
                    spread_pct = ((ask - bid) / ((ask + bid) / 2)) * 100
                    return spread_pct

            except (ValueError, ConnectionError) as e:
                _log.debug("spread_provider_error", extra={"symbol": symbol, "error": str(e)})

            return None

        return spread_provider

    @staticmethod
    async def create_risk_manager(settings: Any, broker: Any) -> RiskManager:
        """Create risk manager with spread provider."""
        spread_provider = await ComponentFactory.create_spread_provider(broker)
        config = RiskConfig.from_settings(settings, spread_provider=spread_provider)
        return RiskManager(config)

    @staticmethod
    def create_protective_exits(
        broker: Any, storage: StorageFacade, bus: UnifiedEventBus, settings: Any
    ) -> ProtectiveExits:
        """Create protective exits handler."""
        return ProtectiveExits(
            broker=broker,
            storage=storage,
            bus=bus,
            settings=settings,
        )

    @staticmethod
    def create_health_checker(
        storage: StorageFacade, broker: Any, bus: UnifiedEventBus, settings: Any
    ) -> HealthChecker:
        """Create health checker."""
        return HealthChecker(
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings,
        )

    @staticmethod
    def create_dead_mans_switch(bus: UnifiedEventBus, broker: Any, settings: Any) -> DeadMansSwitch:
        """Create dead man's switch."""
        return DeadMansSwitch(
            bus=bus,
            broker=broker,
            settings=settings,
        )

    @staticmethod
    def create_instance_lock(settings: Any) -> InstanceLock:
        """Create instance lock."""
        db_path = getattr(settings, "DB_PATH", "app.db")
        lock_path = f"{db_path}.lock"
        return InstanceLock(lock_path)


class OrchestratorFactory:
    """Factory for creating orchestrators."""

    @staticmethod
    def parse_symbols(settings: Any) -> list[str]:
        """Parse symbols from settings."""
        symbols_str = getattr(settings, "SYMBOLS", "") or getattr(settings, "SYMBOL", "BTC/USDT")

        symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

        if not symbols:
            symbols = ["BTC/USDT"]

        return symbols

    @staticmethod
    def create_orchestrators(
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
        symbols = OrchestratorFactory.parse_symbols(settings)

        for symbol in symbols:
            orchestrator = Orchestrator(
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
            orchestrators[symbol] = orchestrator
            _log.info("orchestrator_created", extra={"symbol": symbol})

        return orchestrators

    @staticmethod
    async def auto_start_orchestrators(orchestrators: dict[str, Orchestrator], settings: Any) -> None:
        """Auto-start orchestrators if configured."""
        if not int(getattr(settings, "TRADER_AUTOSTART", 0)):
            return

        for symbol, orchestrator in orchestrators.items():
            try:
                await orchestrator.start()
                _log.info("orchestrator_auto_started", extra={"symbol": symbol})
            except (RuntimeError, AttributeError) as e:
                _log.error(
                    "orchestrator_auto_start_failed", extra={"symbol": symbol, "error": str(e)}, exc_info=True
                )


class TelegramIntegration:
    """Telegram integration setup."""

    @staticmethod
    def setup(bus: UnifiedEventBus, settings: Any) -> None:
        """Setup Telegram integrations if enabled."""
        if not int(getattr(settings, "TELEGRAM_ENABLED", 0)):
            _log.info("telegram.disabled")
            return

        try:
            TelegramIntegration._setup_alerts(bus, settings)
            TelegramIntegration._setup_bot_commands(settings)

        except ImportError as e:
            _log.warning("telegram_modules_not_found", extra={"error": str(e)})
        except (RuntimeError, ValueError) as e:
            _log.error("telegram_setup_failed", extra={"error": str(e)}, exc_info=True)

    @staticmethod
    def _setup_alerts(bus: UnifiedEventBus, settings: Any) -> None:
        """Setup Telegram alerts."""
        from crypto_ai_bot.app.telegram_alerts import attach_alerts

        attach_alerts(bus, settings)
        _log.info("telegram.alerts.attached")

    @staticmethod
    def _setup_bot_commands(settings: Any) -> None:
        """Setup bot commands if enabled."""
        if int(getattr(settings, "TELEGRAM_BOT_COMMANDS_ENABLED", 0)):
            _log.info("telegram.commands.ready")


class ContainerBuilder:
    """Builder for application container."""

    def __init__(self):
        self.factory = ComponentFactory()
        self.orch_factory = OrchestratorFactory()
        self.telegram = TelegramIntegration()

    async def build(self) -> AppContainer:
        """Build the application container."""
        _log.info("compose.start")

        # Load settings
        settings = await self._load_settings()

        # Create core components
        bus = self.factory.create_bus(settings)
        storage = self.factory.create_storage(settings)
        broker = self.factory.create_broker(settings)

        # Create application components
        risk = await self.factory.create_risk_manager(settings, broker)
        exits = self.factory.create_protective_exits(broker, storage, bus, settings)
        health = self.factory.create_health_checker(storage, broker, bus, settings)
        dms = self.factory.create_dead_mans_switch(bus, broker, settings)
        instance_lock = self.factory.create_instance_lock(settings)

        # Acquire instance lock
        if not instance_lock.acquire():
            _log.warning("instance_lock_already_held")

        # Create orchestrators
        orchestrators = self.orch_factory.create_orchestrators(
            settings, storage, broker, bus, risk, exits, health, dms
        )

        # Setup integrations
        self.telegram.setup(bus, settings)

        # Auto-start if configured
        await self.orch_factory.auto_start_orchestrators(orchestrators, settings)

        _log.info("compose.done")

        container = AppContainer(
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
        return container

    async def _load_settings(self) -> Any:
        """Load application settings."""
        from crypto_ai_bot.core.infrastructure.settings import Settings

        return Settings.load()


# Public API functions
async def build_container_async() -> AppContainer:
    """Asynchronously build the application container."""
    builder = ContainerBuilder()
    container = await builder.build()
    return container


def compose() -> AppContainer:
    """Synchronously build the application container."""
    return asyncio.run(build_container_async())