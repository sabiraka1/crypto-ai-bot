"""
Dependency Injection composition.
Assembly of all system components.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import StorageFacade
from crypto_ai_bot.core.infrastructure.storage.sqlite_adapter import SQLiteAdapter
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.safety.instance_lock import InstanceLock
from crypto_ai_bot.core.infrastructure.settings import get_settings
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AppContainer:
    """
    Application dependency container.
    Holds all initialized components.
    """
    settings: Any
    storage: StorageFacade
    broker: Any
    bus: AsyncEventBus
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    dms: DeadMansSwitch
    instance_lock: InstanceLock
    orchestrators: dict[str, Orchestrator]
    
    async def start(self) -> None:
        """Start all components"""
        # Start event bus
        await self.bus.start()
        
        # Start protective exits
        await self.exits.start()
        
        # Start health checker
        await self.health.start()
        
        # Start dead man's switch if enabled
        if getattr(self.settings, "DMS_ENABLED", False):
            await self.dms.start()
        
        # Auto-start orchestrators if configured
        if getattr(self.settings, "AUTOSTART", False):
            for symbol, orch in self.orchestrators.items():
                try:
                    await orch.start()
                    logger.info(f"Orchestrator auto-started for {symbol}")
                except Exception as e:
                    logger.error(f"Failed to auto-start orchestrator for {symbol}: {e}")
    
    async def stop(self) -> None:
        """Stop all components gracefully"""
        # Stop orchestrators
        for orch in self.orchestrators.values():
            try:
                await orch.stop()
            except Exception as e:
                logger.error(f"Error stopping orchestrator: {e}")
        
        # Stop other components
        await self.exits.stop()
        await self.health.stop()
        await self.dms.stop()
        await self.bus.stop()
        
        # Release instance lock
        self.instance_lock.release()


class ComponentFactory:
    """Factory for creating application components"""
    
    @staticmethod
    def create_storage(settings: Any) -> StorageFacade:
        """Create storage facade with SQLite backend"""
        db_path = getattr(settings, "DB_PATH", "./data/trader.sqlite3")
        logger.info(f"Initializing SQLite storage at {db_path}")
        
        adapter = SQLiteAdapter(db_path)
        return StorageFacade(adapter)
    
    @staticmethod
    def create_broker(settings: Any) -> Any:
        """Create broker based on mode (paper/live)"""
        mode = getattr(settings, "MODE", "paper")
        exchange = getattr(settings, "EXCHANGE", "gateio")
        
        logger.info(f"Creating {mode} broker for {exchange}")
        return make_broker(mode=mode, exchange=exchange, settings=settings)
    
    @staticmethod
    def create_event_bus(settings: Any) -> AsyncEventBus:
        """Create event bus (in-memory or Redis)"""
        bus_url = getattr(settings, "EVENT_BUS_URL", "")
        
        if bus_url.startswith("redis://"):
            # TODO: Implement Redis bus
            logger.info("Redis event bus not yet implemented, using in-memory")
        
        # In-memory bus with deduplication
        return AsyncEventBus(
            enable_dedupe=True,
            topic_concurrency=64,
            max_attempts=3,
            backoff_base_ms=250
        )
    
    @staticmethod
    async def create_risk_manager(settings: Any, broker: Any) -> RiskManager:
        """Create risk manager with spread provider"""
        
        # Create spread provider function
        async def spread_provider(symbol: str) -> Optional[float]:
            try:
                ticker = await broker.fetch_ticker(symbol)
                bid = float(ticker.get("bid", 0))
                ask = float(ticker.get("ask", 0))
                if bid > 0 and ask > 0:
                    return ((ask - bid) / ((ask + bid) / 2)) * 100
            except Exception as e:
                logger.debug(f"Failed to get spread for {symbol}: {e}")
            return None
        
        # Create risk config from settings
        config = RiskConfig.from_settings(settings, spread_provider=spread_provider)
        return RiskManager(config)
    
    @staticmethod
    def create_protective_exits(
        broker: Any,
        storage: StorageFacade,
        bus: AsyncEventBus,
        settings: Any
    ) -> ProtectiveExits:
        """Create protective exits handler"""
        return ProtectiveExits(
            broker=broker,
            storage=storage,
            bus=bus,
            settings=settings
        )
    
    @staticmethod
    def create_health_checker(
        storage: StorageFacade,
        broker: Any,
        bus: AsyncEventBus,
        settings: Any
    ) -> HealthChecker:
        """Create health checker"""
        return HealthChecker(
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings
        )
    
    @staticmethod
    def create_dead_mans_switch(
        bus: AsyncEventBus,
        broker: Any,
        settings: Any
    ) -> DeadMansSwitch:
        """Create dead man's switch"""
        return DeadMansSwitch(
            bus=bus,
            broker=broker,
            settings=settings
        )
    
    @staticmethod
    def create_instance_lock(settings: Any) -> InstanceLock:
        """Create instance lock to prevent double launch"""
        db_path = getattr(settings, "DB_PATH", "./data/trader.sqlite3")
        lock_path = f"{db_path}.lock"
        return InstanceLock(lock_path)


class OrchestratorFactory:
    """Factory for creating orchestrators"""
    
    @staticmethod
    def parse_symbols(settings: Any) -> list[str]:
        """Parse trading symbols from settings"""
        symbols = getattr(settings, "SYMBOLS", [])
        if not symbols:
            return ["BTC/USDT"]  # Default symbol
        return symbols
    
    @staticmethod
    def create_orchestrators(
        settings: Any,
        storage: StorageFacade,
        broker: Any,
        bus: AsyncEventBus,
        risk: RiskManager,
        exits: ProtectiveExits,
        health: HealthChecker,
        dms: DeadMansSwitch
    ) -> dict[str, Orchestrator]:
        """Create orchestrators for all configured symbols"""
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
                dms=dms
            )
            orchestrators[symbol] = orchestrator
            logger.info(f"Created orchestrator for {symbol}")
        
        return orchestrators


async def compose() -> AppContainer:
    """
    Main composition function.
    Creates and wires all components together.
    """
    logger.info("Starting dependency injection composition")
    
    # Load settings
    settings = get_settings()
    
    # Create core components
    storage = ComponentFactory.create_storage(settings)
    broker = ComponentFactory.create_broker(settings)
    bus = ComponentFactory.create_event_bus(settings)
    
    # Create application components
    risk = ComponentFactory.create_risk_manager(settings, storage)
    exits = ComponentFactory.create_protective_exits(broker, storage, bus, settings)
    health = ComponentFactory.create_health_checker(storage, broker, bus, settings)
    dms = ComponentFactory.create_dead_mans_switch(bus, broker, settings)
    instance_lock = ComponentFactory.create_instance_lock(settings)
    
    # Acquire instance lock
    if not instance_lock.acquire():
        raise RuntimeError("Another instance is already running")
    
    # Create orchestrators for all symbols
    orchestrators = OrchestratorFactory.create_orchestrators(
        settings, storage, broker, bus, risk, exits, health, dms
    )
    
    # Create container
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
        orchestrators=orchestrators
    )
    
    logger.info("Dependency injection composition completed")
    return container


# Synchronous wrapper for compatibility
def compose_sync() -> AppContainer:
    """Synchronous wrapper for compose()"""
    return asyncio.run(compose())


__all__ = [
    "AppContainer",
    "ComponentFactory",
    "OrchestratorFactory",
    "compose",
    "compose_sync",
]