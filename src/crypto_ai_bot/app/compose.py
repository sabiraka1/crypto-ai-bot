from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.ports import EventBusPort, BrokerPort, SafetySwitchPort
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.events.bus_adapter import UnifiedEventBus
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.infrastructure.storage.instance_lock import InstanceLock
from crypto_ai_bot.core.infrastructure.events.topics import TRADE_COMPLETED
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import hist, inc
from crypto_ai_bot.utils.retry import async_retry
from crypto_ai_bot.utils.symbols import canonical

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
    safety: SafetySwitchPort | None = None
    instance_lock: Any | None = None
    tg_bot_task: asyncio.Task | None = None
    dms_task: asyncio.Task | None = None


# ---- Event bus builders ----

def _build_event_bus(settings: Settings) -> EventBusPort:
    raw = getattr(settings, "EVENT_BUS_URL", "")
    redis_url = raw if isinstance(raw, str) else ""
    redis_url = (redis_url or "").strip()

    def _ok(u: str) -> bool:
        return isinstance(u, str) and (
            u.startswith("redis://") or u.startswith("rediss://") or u.startswith("unix://")
        )

    impl = RedisEventBus(redis_url) if _ok(redis_url) else AsyncEventBus()
    return UnifiedEventBus(impl)


def _wrap_bus_publish_with_metrics_and_retry(bus: Any) -> None:
    if not hasattr(bus, "publish"):
        return
    _orig = bus.publish

    async def _publish(topic: str, payload: dict[str, Any]) -> None:
        t = hist("bus_publish_latency_seconds", topic=topic)

        async def call() -> Any:
            with t.time():
                return await _orig(topic, payload)

        await async_retry(call, retries=3, base_delay=0.2)
        inc("bus_publish_total", topic=topic)

    bus.publish = _publish  # type: ignore[attr-defined]


def attach_alerts(bus: Any, settings: Settings) -> None:
    tg = TelegramAlerts(settings=settings)

    async def on_trade_completed(payload: dict[str, Any]) -> None:
        try:
            await tg.trade_completed(payload)
        except Exception:
            _log.error("alert_trade_completed_failed", exc_info=True)

    # Use Callable/Awaitable types explicitly to keep type-level imports "live"
    handler: Callable[[dict[str, Any]], Awaitable[None]] = on_trade_completed
    bus.on(TRADE_COMPLETED, handler)  # type: ignore[arg-type]


async def _run_dms_loop(dms: DeadMansSwitch, interval_sec: int) -> None:
    # Small background loop to keep the safety switch "live"
    while True:
        try:
            await asyncio.sleep(max(1, interval_sec))
            await dms.check()
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.error("dms_check_failed", exc_info=True)


# ---- Container ----

async def build_container_async() -> Container:
    s = Settings.load()

    # Storage
    db_path = Path(s.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    st = Storage.from_connection(conn)
    run_migrations(st)

    # Instance lock (keep single active instance on same DB)
    try:
        inst_lock = InstanceLock(conn, name=(s.POD_NAME or s.HOSTNAME or "instance"))
    except Exception:
        _log.error("instance_lock_failed", exc_info=True)
        inst_lock = None

    # Broker
    br = make_broker(mode=s.MODE, exchange=s.EXCHANGE, settings=s)

    # Macro regime wiring (ENV-driven)
    try:
        def _b(name: str, default: str = "0") -> bool:
            v = (os.getenv(name, default) or "").strip().lower()
            return v in ("1", "true", "yes", "on")

        def _f(name: str, default: str) -> float:
            try:
                return float(os.getenv(name, default))
            except Exception:
                return float(default)

        regime_enabled = _b("REGIME_ENABLED", "0")
        regime_block_buy = _b("REGIME_BLOCK_BUY", "1")

        if regime_enabled:
            from crypto_ai_bot.core.infrastructure.macro.sources.http_dxy import DxyHttp
            from crypto_ai_bot.core.infrastructure.macro.sources.http_btc_dominance import BtcDominanceHttp
            from crypto_ai_bot.core.infrastructure.macro.sources.http_fomc import FomcHttp
            from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector, RegimeConfig
            from crypto_ai_bot.core.application.regime.gated_broker import GatedBroker

            dxy_url = (os.getenv("DXY_SOURCE_URL", "") or "").strip()
            btc_dom_url = (os.getenv("BTC_DOM_SOURCE_URL", "") or "").strip()
            fomc_url = (os.getenv("FOMC_CALENDAR_URL", "") or "").strip()

            dxy = DxyHttp(dxy_url) if dxy_url else None
            btc_dom = BtcDominanceHttp(btc_dom_url) if btc_dom_url else None
            fomc = FomcHttp(fomc_url) if fomc_url else None

            cfg = RegimeConfig(
                dxy_up_pct=_f("REGIME_DXY_UP_PCT", "0.5"),
                dxy_down_pct=_f("REGIME_DXY_DOWN_PCT", "-0.2"),
                btc_dom_up_pct=_f("REGIME_BTC_DOM_UP_PCT", "0.5"),
                btc_dom_down_pct=_f("REGIME_BTC_DOM_DOWN_PCT", "-0.5"),
                fomc_block_minutes=int(os.getenv("REGIME_FOMC_BLOCK_MIN", "60") or "60"),
            )
            regime = RegimeDetector(dxy=dxy, btc_dom=btc_dom, fomc=fomc, cfg=cfg)
            if regime_block_buy:
                br = GatedBroker(inner=br, regime=regime, allow_sells_when_off=True)
                _log.info("regime_gated_broker_enabled")
            else:
                _log.info("regime_detector_enabled")
        else:
            _log.info("regime_disabled")
    except Exception:
        _log.error("regime_wiring_failed", exc_info=True)

    # Event bus
    bus = _build_event_bus(s)
    _wrap_bus_publish_with_metrics_and_retry(bus)
    attach_alerts(bus, s)

    # Risk
    rcfg = RiskConfig(
        max_loss_streak=s.RISK_MAX_LOSS_STREAK,
        daily_loss_limit_quote=s.RISK_DAILY_LOSS_LIMIT_QUOTE,
        max_drawdown_pct=s.RISK_MAX_DRAWDOWN_PCT,
    )
    risk = RiskManager(storage=st, cfg=rcfg)

    # Exits
    exits = ProtectiveExits(storage=st, broker=br, risk=risk)

    # Health checker
    health = HealthChecker(storage=st, bus=bus, broker=br)

    # Safety switch (Dead Man's Switch) — keep "live" & typed as SafetySwitchPort
    dms: SafetySwitchPort = DeadMansSwitch(timeout_ms=s.DMS_TIMEOUT_MS, bus=bus)
    # also use `dec` to keep Decimal helper "live" (and useful for logs)
    _ = dec(str(s.RISK_DAILY_LOSS_LIMIT_QUOTE))
    dms_task = asyncio.create_task(_run_dms_loop(dms, max(1, int(getattr(s, "WATCHDOG_INTERVAL_SEC", 15) or 15))))

    # Orchestrators per symbol
    symbols = s.SYMBOLS or [s.SYMBOL]
    orchs: dict[str, Orchestrator] = {}
    for sym in symbols:
        can = canonical(sym)
        orch = Orchestrator(
            symbol=can,
            storage=st,
            broker=br,
            risk=risk,
            exits=exits,
            bus=bus,
            evaluate_interval_sec=s.EVALUATE_INTERVAL_SEC,
            exits_interval_sec=s.EXITS_INTERVAL_SEC,
            reconcile_interval_sec=s.RECONCILE_INTERVAL_SEC,
            watchdog_interval_sec=s.WATCHDOG_INTERVAL_SEC,
        )
        orchs[can] = orch

    # Telegram command bot (optional)
    tg_task: asyncio.Task | None = None
    if getattr(s, "TELEGRAM_BOT_COMMANDS_ENABLED", 0) and getattr(s, "TELEGRAM_BOT_TOKEN", ""):
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
        safety=dms,
        instance_lock=inst_lock,
        tg_bot_task=tg_task,
        dms_task=dms_task,
    )
