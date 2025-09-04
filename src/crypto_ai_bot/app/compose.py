from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.app.subscribers.telegram_alerts import attach_alerts
from crypto_ai_bot.core.application.events_topics import EVT  # noqa: N812
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.ports import SafetySwitchPort
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.bus_adapter import UnifiedEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.safety.instance_lock import InstanceLock
from crypto_ai_bot.core.infrastructure.storage.sqlite_adapter import open_storage
from crypto_ai_bot.settings import Settings
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger("compose")


@dataclass
class Container:
    settings: Any
    storage: Any
    broker: Any
    bus: Any
    risk: Any
    exits: Any
    health: Any
    orchestrators: dict[str, Orchestrator]
    tg_bot_task: asyncio.Task | None
    instance_lock: InstanceLock | None = None


def _open_storage(s: Settings) -> Any:
    return open_storage(path=s.DB_PATH)


def _build_event_bus(s: Settings) -> Any:
    # Choose EventBus by ENV: Redis if EVENT_BUS_URL=redis://..., else in-memory
    url = getattr(s, "EVENT_BUS_URL", "").strip()
    if url and url.startswith("redis://"):  # noqa: SIM108
        impl = RedisEventBus(url)
    else:
        impl = AsyncEventBus()
    return UnifiedEventBus(impl)


def _wrap_bus_publish_with_metrics_and_retry(bus: Any) -> None:
    orig = bus.publish

    async def _pub(topic: str, payload: dict[str, Any]) -> None:
        tries = 0
        while True:
            try:
                await orig(topic, payload)
                return  # noqa: TRY300
            except Exception:  # noqa: BLE001
                tries += 1
                inc("bus_publish_error_total", symbol=payload.get("symbol", ""), topic=topic)
                if tries >= 3:
                    _log.error("bus_publish_failed", extra={"topic": topic}, exc_info=True)
                    raise
                await asyncio.sleep(0.2 * tries)

    bus.publish = _pub  # type: ignore[attr-defined]


def _make_dms_factory(*, st: Any, br: Any, s: Settings, bus: Any) -> Callable[[str], SafetySwitchPort]:
    def _factory(sym: str) -> SafetySwitchPort:
        # Compatibility with AsyncEventBus (pass None if not supported)
        dms_bus = bus if isinstance(bus, AsyncEventBus) else None

        def safe_dec(name: str, default: str = "0") -> Decimal:
            val = getattr(s, name, None)
            if val is None:
                return dec(default)
            try:
                str_val = str(val).strip()
                if not str_val or str_val.lower() in ("none", "null", ""):
                    return dec(default)  # noqa: TRY300
                float(str_val)
                return dec(str_val)  # noqa: TRY300
            except (ValueError, TypeError, AttributeError):
                return dec(default)

        return DeadMansSwitch(
            storage=st,
            broker=br,
            symbol=sym,
            timeout_ms=int(getattr(s, "DMS_TIMEOUT_MS", 120_000) or 120_000),
            rechecks=int(getattr(s, "DMS_RECHECKS", 2) or 2),
            recheck_delay_sec=float(getattr(s, "DMS_RECHECK_DELAY_SEC", 3.0) or 3.0),
            max_impact_pct=safe_dec("DMS_MAX_IMPACT_PCT", "0"),
            bus=dms_bus,
        )

    return _factory


async def build_container_async() -> Container:
    s = Settings.load()
    st = _open_storage(s)
    bus = _build_event_bus(s)
    if hasattr(bus, "start"):
        await bus.start()

    _wrap_bus_publish_with_metrics_and_retry(bus)

    # single-instance lock (to release in shutdown via server.py)
    lock = InstanceLock(
        conn=st.conn,
        app="trader",
        owner=getattr(s, "INSTANCE_ID", "local"),
    )
    assert lock.acquire(ttl_sec=900), "Another instance is already running"
    _log.info("instance_lock_acquired", extra={"owner": getattr(s, "INSTANCE_ID", "local")})

    br = make_broker(exchange=s.EXCHANGE, mode=s.MODE, settings=s)
    risk = RiskManager(RiskConfig.from_settings(s))
    exits = ProtectiveExits(storage=st, broker=br, bus=bus, settings=s)
    health = HealthChecker(storage=st, broker=br, bus=bus, settings=s)

    symbols: list[str] = [canonical(x.strip()) for x in (s.SYMBOLS or "").split(",") if x.strip()] or [
        canonical(s.SYMBOL)
    ]

    orchs: dict[str, Orchestrator] = {}
    make_dms = _make_dms_factory(st=st, br=br, s=s, bus=bus)
    for sym in symbols:
        orchs[sym] = Orchestrator(
            symbol=sym,
            storage=st,
            broker=br,
            risk=risk,
            exits=exits,
            bus=bus,
            settings=s,
            dms=make_dms(sym),
        )

    # Telegram subscribers (alerts) — единый модуль подписок
    attach_alerts(bus, s)

    # Hint for ProtectiveExits + event re-broadcast
    if hasattr(exits, "on_hint") and hasattr(bus, "on"):

        async def _on_trade_completed_hint(evt: dict[str, Any]) -> None:
            try:
                await exits.on_hint(evt)
            except Exception:  # noqa: BLE001
                _log.error("exits_on_hint_failed", extra={"symbol": evt.get("symbol", "")}, exc_info=True)

        bus.on(events_topics.TRADE_COMPLETED, _on_trade_completed_hint)

    # Telegram command bot (incoming commands)
    tg_task: asyncio.Task | None = None
    if getattr(s, "TELEGRAM_BOT_COMMANDS_ENABLED", False) and getattr(s, "TELEGRAM_BOT_TOKEN", ""):
        raw_users = str(getattr(s, "TELEGRAM_ALLOWED_USERS", "") or "").strip()
        users: list[int] = []
        if raw_users:
            try:
                users = [int(x.strip()) for x in raw_users.split(",") if x.strip()]
            except Exception:  # noqa: BLE001
                _log.error("telegram_allowed_users_parse_failed", extra={"raw": raw_users}, exc_info=True)

        container_view = type(
            "C",
            (),
            {
                "storage": st,
                "broker": br,
                "risk": risk,
                "exits": exits,
                "orchestrators": orchs,
                "health": health,
            },
        )()
        bot = TelegramBotCommands(
            bot_token=s.TELEGRAM_BOT_TOKEN,
            allowed_users=users,
            container=container_view,
            default_symbol=symbols[0],
        )
        tg_task = asyncio.create_task(bot.run())
        _log.info("telegram_bot_enabled")

    return Container(
        settings=s,
        storage=st,
        broker=br,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        orchestrators=orchs,
        tg_bot_task=tg_task,
        instance_lock=lock,  # to release in shutdown (server.py)
    )
