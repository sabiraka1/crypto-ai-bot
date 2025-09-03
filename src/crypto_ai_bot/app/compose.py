from __future__ import annotations

import asyncio
from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Awaitable

from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.app.subscribers.telegram_alerts import attach_alerts
from crypto_ai_bot.core.application import events_topics as EVT  # â† Ğ´Ğ¾Ğ±Ğ°Ğ²Ğ»ĞµĞ½Ğ¾
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.ports import SafetySwitchPort, EventBusPort, BrokerPort
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.regime.gated_broker import GatedBroker
from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector, RegimeConfig
from crypto_ai_bot.core.infrastructure.macro.sources.http_dxy import DxyHttp
from crypto_ai_bot.core.infrastructure.macro.sources.http_btc_dominance import BtcDominanceHttp
from crypto_ai_bot.core.infrastructure.macro.sources.http_fomc import FomcHttp
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.events.bus_adapter import UnifiedEventBus
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import hist, inc
from crypto_ai_bot.utils.retry import async_retry
from crypto_ai_bot.utils.symbols import canonical
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: BrokerPort
    bus: EventBusPort
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    orchestrators: dict[str, Orchestrator]
    tg_bot_task: asyncio.Task[None] | None = None


def _open_storage(settings: Settings) -> Storage:
    db_path = settings.DB_PATH
    db_dir = os.path.dirname(db_path) or "."
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    run_migrations(
        conn,
        now_ms=now_ms(),
        db_path=db_path,
        do_backup=True,
        backup_retention_days=int(getattr(settings, "BACKUP_RETENTION_DAYS", 30) or 30),
    )
    return Storage.from_connection(conn)


def _build_event_bus(settings: Settings) -> EventBusPort:
    redis_url = str(getattr(settings, "EVENT_BUS_URL", "") or "").strip()
    impl = RedisEventBus(redis_url) if redis_url else AsyncEventBus()
    return UnifiedEventBus(impl)


def _wrap_bus_publish_with_metrics_and_retry(bus: Any) -> None:
    """ĞĞ±Ğ¾Ñ€Ğ°Ñ‡Ğ¸Ğ²Ğ°ĞµĞ¼ publish Ñ€ĞµÑ‚Ñ€Ğ°ÑĞ¼Ğ¸ Ğ¸ Ğ³Ğ¸ÑÑ‚Ğ¾Ğ³Ñ€Ğ°Ğ¼Ğ¼Ğ¾Ğ¹, Ğ½Ğµ Ğ¼ĞµĞ½ÑÑ Ğ¸Ğ½Ñ‚ĞµÑ€Ñ„ĞµĞ¹Ñ EventBus."""
    if not hasattr(bus, "publish"):
        return
    _orig = bus.publish

    async def _publish(topic: str, payload: dict[str, Any]) -> None:
        t = hist("bus_publish_latency_seconds", topic=topic)

        async def call() -> Any:
            if t:
                with t.time():
                    return await _orig(topic, payload)
            else:
                return await _orig(topic, payload)

        await async_retry(call, retries=3, base_delay=0.2)
        inc("bus_publish_total", topic=topic)

    bus.publish = _publish  # type: ignore[attr-defined]


def _maybe_wrap_with_regime(broker: BrokerPort, settings: Settings) -> BrokerPort:
    """Ğ’ĞºĞ»ÑÑ‡Ğ°ĞµĞ¼ regime-gating Ğ¿Ñ€Ğ¸ REGIME_ENABLED=1 (risk_off Ğ±Ğ»Ğ¾ĞºĞ¸Ñ€ÑƒĞµÑ‚ Ğ½Ğ¾Ğ²Ñ‹Ğµ Ğ²Ñ…Ğ¾Ğ´Ñ‹)."""
    if not bool(getattr(settings, "REGIME_ENABLED", False)):
        return broker

    # URLs Ğ¸ Ñ‚Ğ°Ğ¹Ğ¼Ğ°ÑƒÑ‚Ñ‹ Ğ¸ÑÑ‚Ğ¾Ñ‡Ğ½Ğ¸ĞºĞ¾Ğ² â€” Ğ¸Ğ· ENV, Ñ Ğ±ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ñ‹Ğ¼Ğ¸ Ğ´ĞµÑ„Ğ¾Ğ»Ñ‚Ğ°Ğ¼Ğ¸
    dxy_url = str(getattr(settings, "REGIME_DXY_URL", "") or "")
    btc_dom_url = str(getattr(settings, "REGIME_BTC_DOM_URL", "") or "")
    fomc_url = str(getattr(settings, "REGIME_FOMC_URL", "") or "")
    to = float(getattr(settings, "REGIME_HTTP_TIMEOUT_SEC", 5.0) or 5.0)

    dxy = DxyHttp(dxy_url, timeout_sec=to) if dxy_url else None
    btd = BtcDominanceHttp(btc_dom_url, timeout_sec=to) if btc_dom_url else None
    fomc = FomcHttp(fomc_url, timeout_sec=to) if fomc_url else None

    cfg = RegimeConfig(
        dxy_change_limit_pct=float(getattr(settings, "REGIME_DXY_LIMIT_PCT", 0.35) or 0.35),
        btc_dom_change_limit_pct=float(getattr(settings, "REGIME_BTC_DOM_LIMIT_PCT", 0.6) or 0.6),
        fomc_blocks_hours=int(getattr(settings, "REGIME_FOMC_BLOCK_HOURS", 8) or 8),
    )
    detector = RegimeDetector(dxy=dxy, btc_dom=btd, fomc=fomc, config=cfg)

    _log.info("regime_gating_enabled", extra={"cfg": cfg.__dict__})
    return GatedBroker(inner=broker, regime=detector, allow_sells_when_off=True)


async def build_container_async() -> Container:
    s = Settings.load()
    st = _open_storage(s)
    bus = _build_event_bus(s)
    if hasattr(bus, "start"):
        await bus.start()

    _wrap_bus_publish_with_metrics_and_retry(bus)

    br_raw = make_broker(exchange=s.EXCHANGE, mode=s.MODE, settings=s)
    br = _maybe_wrap_with_regime(br_raw, s)

    risk = RiskManager(RiskConfig.from_settings(s))
    exits = ProtectiveExits(storage=st, broker=br, bus=bus, settings=s)
    health = HealthChecker(storage=st, broker=br, bus=bus, settings=s)

    symbols: list[str] = [canonical(x.strip()) for x in (s.SYMBOLS or "").split(",") if x.strip()] or [canonical(s.SYMBOL)]
    orchs: dict[str, Orchestrator] = {}

    def _make_dms(sym: str) -> SafetySwitchPort:
        dms_bus = bus if isinstance(bus, AsyncEventBus) else None

        def safe_dec(name: str, default: str = "0") -> Decimal:
            val = getattr(s, name, None)
            if val is None:
                return dec(default)
            try:
                str_val = str(val).strip()
                if not str_val or str_val.lower() in ("none", "null", ""):
                    return dec(default)
                float(str_val)  # Ğ²Ğ°Ğ»Ğ¸Ğ´Ğ°Ñ†Ğ¸Ñ
                return dec(str_val)
            except Exception:
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

    for sym in symbols:
        orchs[sym] = Orchestrator(
            symbol=sym,
            storage=st,
            broker=br,
            bus=bus,
            risk=risk,
            exits=exits,
            health=health,
            settings=s,
            dms=_make_dms(sym),
        )

    # ĞŸĞ¾Ğ´Ğ¿Ğ¸ÑÑ‡Ğ¸Ğº Telegram (Ğ°Ğ»Ñ‘Ñ€Ñ‚Ñ‹ Ğ¸Ğ· EventBus â†’ Telegram)
    attach_alerts(bus, s)

    # Hint Ğ´Ğ»Ñ ProtectiveExits
    if hasattr(exits, "on_hint") and hasattr(bus, "on"):
        bus.on("exits.hint", exits.on_hint)

        async def _on_trade_completed_hint(evt: dict[str, Any]) -> None:
            try:
                await exits.on_hint(evt)
            except Exception:
                _log.error("exits_on_hint_failed", extra={"symbol": evt.get("symbol", "")}, exc_info=True)

        bus.on(EVT.TRADE_COMPLETED, _on_trade_completed_hint)

    # ĞšĞ¾Ğ¼Ğ°Ğ½Ğ´Ğ½Ñ‹Ğ¹ Telegram-Ğ±Ğ¾Ñ‚ (Ğ²Ñ…Ğ¾Ğ´ÑÑ‰Ğ¸Ğµ ĞºĞ¾Ğ¼Ğ°Ğ½Ğ´Ñ‹)
    tg_task: asyncio.Task[None] | None = None
    if getattr(s, "TELEGRAM_BOT_COMMANDS_ENABLED", False) and getattr(s, "TELEGRAM_BOT_TOKEN", ""):
        raw_users = str(getattr(s, "TELEGRAM_ALLOWED_USERS", "") or "").strip()
        users: list[int] = []
        if raw_users:
            try:
                users = [int(x.strip()) for x in raw_users.split(",") if x.strip()]
            except Exception:
                _log.error("telegram_allowed_users_parse_failed", extra={"raw": raw_users}, exc_info=True)

        container_view = type(
            "C",
            (),
            {"storage": st, "broker": br, "risk": risk, "exits": exits, "orchestrators": orchs, "health": health},
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
    )
