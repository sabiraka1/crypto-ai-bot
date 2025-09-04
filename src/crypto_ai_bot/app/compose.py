from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# NEW: телеграм-бот всегда стартует
from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.multi_bus import MirrorRules, MultiEventBus
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
    bus: Any  # MultiEventBus | AsyncEventBus | RedisEventBus
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    dms: DeadMansSwitch
    instance_lock: InstanceLock
    orchestrators: dict[str, Orchestrator]
    telegram_task: asyncio.Task | None = None  # NEW: фонова задача бота


class ComponentFactory:
    """Factory for creating application components."""

    @staticmethod
    def create_bus(settings: Any) -> MultiEventBus:
        """
        Create multi-event bus:
          - локально: AsyncEventBus (быстрые подписчики внутри процесса)
          - зеркалирование во внешнюю шину: RedisEventBus при EVENT_BUS_URL='redis://...'
        """
        url = str(getattr(settings, "EVENT_BUS_URL", "") or "")
        include_csv = str(getattr(settings, "EVENT_BUS_INCLUDE", "trade.,orders.,health.") or "")
        exclude_csv = str(getattr(settings, "EVENT_BUS_EXCLUDE", "__") or "")

        include = [s.strip() for s in include_csv.split(",") if s.strip()]
        exclude = [s.strip() for s in exclude_csv.split(",") if s.strip()]

        # локальная шина с дедупликацией
        local_bus = AsyncEventBus(enable_dedupe=True, topic_concurrency=64)

        remote_bus = None
        if url.startswith("redis://"):
            _log.info("event_bus.redis.enabled", extra={"url": url})
            remote_bus = RedisEventBus(url=url)
        else:
            _log.info("event_bus.memory.enabled")

        rules = MirrorRules(include=tuple(include), exclude=tuple(exclude))
        return MultiEventBus(local=local_bus, remote=remote_bus, rules=rules, inject_trace=True)

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
        return make_broker(
            mode=getattr(settings, "MODE", "paper"),
            exchange=getattr(settings, "EXCHANGE", "gateio"),
            settings=settings,
        )

    @staticmethod
    async def create_spread_provider(broker: Any) -> Callable[[str], Awaitable[float | None]]:
        """Create spread provider function."""

        async def spread_provider(symbol: str) -> float | None:
            try:
                ticker = await broker.fetch_ticker(symbol)
                bid = float(ticker.get("bid", 0))
                ask = float(ticker.get("ask", 0))
                if bid > 0 and ask > 0:
                    return ((ask - bid) / ((ask + bid) / 2)) * 100
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
        broker: Any, storage: StorageFacade, bus: Any, settings: Any
    ) -> ProtectiveExits:
        """Create protective exits handler."""
        return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)

    @staticmethod
    def create_health_checker(storage: StorageFacade, broker: Any, bus: Any, settings: Any) -> HealthChecker:
        """Create health checker."""
        return HealthChecker(storage=storage, broker=broker, bus=bus, settings=settings)

    @staticmethod
    def create_dead_mans_switch(bus: Any, broker: Any, settings: Any) -> DeadMansSwitch:
        """Create dead man's switch."""
        return DeadMansSwitch(bus=bus, broker=broker, settings=settings)

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
        bus: Any,
        risk: RiskManager,
        exits: ProtectiveExits,
        health: HealthChecker,
        dms: DeadMansSwitch,
    ) -> dict[str, Orchestrator]:
        """Create orchestrators for configured symbols."""
        orchestrators: dict[str, Orchestrator] = {}
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


class ContainerBuilder:
    """Builder for application container."""

    def __init__(self):
        self.factory = ComponentFactory()
        self.orch_factory = OrchestratorFactory()

    async def build(self) -> AppContainer:
        """Build the application container."""
        _log.info("compose.start")

        # Load settings
        settings = await self._load_settings()

        # Create core components
        bus = self.factory.create_bus(settings)
        storage = self.factory.create_storage(settings)
        broker = self.factory.create_broker(settings)

        # Start bus (инициализация Redis-клиента, если включён)
        try:
            await bus.start()
        except Exception:
            _log.warning("bus_start_failed", exc_info=True)

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

        # NEW: Telegram-бот — всегда поднимаем фоновую задачу
        telegram_task = None
        try:
            default_symbol = OrchestratorFactory.parse_symbols(settings)[0]
            allowed_users = _parse_allowed_users(getattr(settings, "TELEGRAM_ALLOWED_USERS", ""))
            bot_token = str(getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "")
            long_poll = int(getattr(settings, "TELEGRAM_LONG_POLL", 30) or 30)

            bot = TelegramBotCommands(
                bot_token=bot_token,
                allowed_users=allowed_users,
                container=None,  # заполним ссылкой на контейнер после сборки
                default_symbol=default_symbol,
                long_poll_sec=long_poll,
            )

            # Временная заглушка контейнера, заменим после return
            # (боту нужен доступ к orchestrators внутри контейнера)
            _pending_bot_holder["bot"] = bot  # type: ignore[name-defined]
            telegram_task = asyncio.create_task(bot.run())
            _log.info("telegram_bot_autostarted", extra={"long_poll": long_poll})
        except Exception:
            _log.warning("telegram_bot_autostart_failed", exc_info=True)

        # Авто-старт оркестраторов (если включено)
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
            telegram_task=telegram_task,
        )

        # Дадим боту доступ к уже собранному контейнеру
        try:
            bot = _pending_bot_holder.pop("bot", None)  # type: ignore[name-defined]
            if bot is not None:
                bot.container = container
        except Exception:
            pass

        return container

    async def _load_settings(self) -> Any:
        """Load application settings."""
        from crypto_ai_bot.core.infrastructure.settings import Settings

        return Settings.load()


_pending_bot_holder: dict[str, Any] = {}  # простая передача ссылки на бота между стадиями


# Helpers
def _parse_allowed_users(value: str) -> list[int]:
    if not value:
        return []
    res: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            res.append(int(part))
        except ValueError:
            continue
    return res


# Public API
async def build_container_async() -> AppContainer:
    """Asynchronously build the application container."""
    builder = ContainerBuilder()
    return await builder.build()


def compose() -> AppContainer:
    """Synchronously build the application container."""
    return asyncio.run(build_container_async())
