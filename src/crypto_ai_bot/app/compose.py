from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.ports import SafetySwitchPort, EventBusPort, BrokerPort
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.regime.gated_broker import GatedBroker
from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector, RegimeConfig
from crypto_ai_bot.core.infrastructure.macro.sources.http_dxy import DxyHttp
from crypto_ai_bot.core.infrastructure.macro.sources.http_btc_dominance import BtcDominanceHttp  # Исправлено
from crypto_ai_bot.core.infrastructure.macro.sources.http_fomc import FomcHttp
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
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

# ... остальной код без изменений, только исправлены использования класса:

async def build_container_async() -> Container:
    # ... код до regime ...
    
    # ---- Regime (по флагу) ----
    regime_enabled = bool(getattr(s, "REGIME_ENABLED", False))
    regime = None
    broker: BrokerPort = base_broker
    if regime_enabled:
        dxy_url = str(getattr(s, "DXY_API_URL", "") or "")
        btc_url = str(getattr(s, "BTC_DOM_API_URL", "") or "")
        fomc_url = str(getattr(s, "FOMC_API_URL", "") or "")
        dxy = DxyHttp(dxy_url) if dxy_url else None
        btd = BtcDominanceHttp(btc_url) if btc_url else None  # Исправлено имя
        fomc = FomcHttp(fomc_url) if fomc_url else None
        regime = RegimeDetector(dxy=dxy, btc_dom=btd, fomc=fomc, cfg=RegimeConfig())
        broker = GatedBroker(inner=base_broker, regime=regime, allow_sells_when_off=True)
    
    # ... остальной код без изменений
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
    tg_bot_task: asyncio.Task | None = None

def _open_storage(settings: Settings) -> Storage:
    db_path = settings.DB_PATH
    db_dir = os.path.dirname(db_path) or "."
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=True,
                   backup_retention_days=int(getattr(settings, "BACKUP_RETENTION_DAYS", 30) or 30))
    return Storage.from_connection(conn)

def _build_event_bus(settings: Settings) -> EventBusPort:
    redis_url = getattr(settings, "EVENT_BUS_URL", "") or ""
    if redis_url:
        return RedisEventBus(redis_url)
    return AsyncEventBus()

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
    tg = TelegramAlerts(
        bot_token=getattr(settings, "TELEGRAM_BOT_TOKEN", ""),
        chat_id=getattr(settings, "TELEGRAM_CHAT_ID", ""),
    )
    if not tg.enabled():
        _log.info("telegram_alerts_disabled")
        return

    async def _send(text: str) -> None:
        try:
            ok = await tg.send(text)
            if not ok:
                _log.warning("telegram_send_not_ok")
        except Exception:
            _log.error("telegram_send_exception", exc_info=True)

    def _sub(topic: str, coro: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        for attr in ("subscribe", "on"):
            if hasattr(bus, attr):
                try:
                    getattr(bus, attr)(topic, coro)
                    return
                except Exception:
                    _log.error("bus_subscribe_failed", extra={"topic": topic}, exc_info=True)
        _log.error("bus_has_no_subscribe_api")

    async def on_auto_paused(evt: dict[str, Any]) -> None:
        inc("orchestrator_auto_paused_total", symbol=evt.get("symbol", ""))
        await _send(f"⚠️ <b>AUTO-PAUSE</b> {evt.get('symbol','')}\nПричина: <code>{evt.get('reason','')}</code>")

    async def on_auto_resumed(evt: dict[str, Any]) -> None:
        inc("orchestrator_auto_resumed_total", symbol=evt.get("symbol", ""))
        await _send(f"🟢 <b>AUTO-RESUME</b> {evt.get('symbol','')}\nПричина: <code>{evt.get('reason','')}</code>")

    async def on_pos_mm(evt: dict[str, Any]) -> None:
        inc("reconcile_position_mismatch_total", symbol=evt.get("symbol", ""))
        await _send(
            "🔄 <b>RECONCILE</b> {s}\nБиржа: <code>{b}</code>\nЛокально: <code>{l}</code>".format(
                s=evt.get("symbol", ""), b=evt.get("exchange", ""), l=evt.get("local", "")
            )
        )

    async def on_dms_triggered(evt: dict[str, Any]) -> None:
        inc("dms_triggered_total", symbol=evt.get("symbol", ""))
        await _send(f"🛑 <b>DMS TRIGGERED</b> {evt.get('symbol','')}\nПродано базового: <code>{evt.get('amount','')}</code>")

    async def on_dms_skipped(evt: dict[str, Any]) -> None:
        inc("dms_skipped_total", symbol=evt.get("symbol", ""))
        await _send(f"⛔ <b>DMS SKIPPED</b> {evt.get('symbol','')}\nПадение: <code>{evt.get('drop_pct','')}%</code>")

    async def on_trade_completed(evt: dict[str, Any]) -> None:
        inc("trade_completed_total", symbol=evt.get("symbol", ""), side=evt.get("side", ""))
        s = evt.get("symbol", "")
        side = evt.get("side", "")
        cost = evt.get("cost", "")
        fee = evt.get("fee_quote", "")
        price = evt.get("price", "")
        amt = evt.get("amount", "")
        await _send(f"✅ <b>TRADE</b> {s} {side.upper()}\nAmt: <code>{amt}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>")

    async def on_trade_failed(evt: dict[str, Any]) -> None:
        inc("trade_failed_total", symbol=evt.get("symbol", ""), reason=evt.get("error", ""))
        await _send(f"❌ <b>TRADE FAILED</b> {evt.get('symbol','')}\n<code>{evt.get('error','')}</code>")

    async def on_settled(evt: dict[str, Any]) -> None:
        inc("trade_settled_total", symbol=evt.get("symbol", ""), side=evt.get("side", ""))
        await _send(f"📦 <b>SETTLED</b> {evt.get('symbol','')} {evt.get('side','').upper()} id=<code>{evt.get('order_id','')}</code>")

    async def on_settlement_timeout(evt: dict[str, Any]) -> None:
        inc("trade_settlement_timeout_total", symbol=evt.get("symbol", ""))
        await _send(f"⏱️ <b>SETTLEMENT TIMEOUT</b> {evt.get('symbol','')} id=<code>{evt.get('order_id','')}</code>")

    async def on_budget_exceeded(evt: dict[str, Any]) -> None:
        inc("budget_exceeded_total", symbol=evt.get("symbol", ""), type=evt.get("type", ""))
        s = evt.get("symbol", "")
        kind = evt.get("type", "")
        detail = f"count_5m={evt.get('count_5m','')}/{evt.get('limit','')}" if kind == "max_orders_5m" else f"turnover={evt.get('turnover','')}/{evt.get('limit','')}"
        await _send(f"⏳ <b>BUDGET</b> {s} превышен ({kind})\n{detail}")

    async def on_trade_blocked(evt: dict[str, Any]) -> None:
        inc("trade_blocked_total", symbol=evt.get("symbol", ""), reason=evt.get("reason", ""))
        await _send(f"🚫 <b>BLOCKED</b> {evt.get('symbol','')}\nПричина: <code>{evt.get('reason','')}</code>")

    async def on_broker_error(evt: dict[str, Any]) -> None:
        inc("broker_error_total", symbol=evt.get("symbol", ""))
        await _send(f"🧯 <b>BROKER ERROR</b> {evt.get('symbol','')}\n<code>{evt.get('error','')}</code>")

    for topic, handler in [
        ("orchestrator.auto_paused", on_auto_paused),
        ("orchestrator.auto_resumed", on_auto_resumed),
        ("reconcile.position_mismatch", on_pos_mm),
        ("safety.dms.triggered", on_dms_triggered),
        ("safety.dms.skipped", on_dms_skipped),
        ("trade.completed", on_trade_completed),
        ("trade.failed", on_trade_failed),
        ("trade.settled", on_settled),
        ("trade.settlement_timeout", on_settlement_timeout),
        ("budget.exceeded", on_budget_exceeded),
        ("trade.blocked", on_trade_blocked),
        ("broker.error", on_broker_error),
    ]:
        _sub(topic, handler)

    _log.info("telegram_alerts_enabled")

async def build_container_async() -> Container:
    s = Settings.load()
    st = _open_storage(s)
    bus = _build_event_bus(s)
    if hasattr(bus, "start"):
        await bus.start()
    _wrap_bus_publish_with_metrics_and_retry(bus)

    base_broker = make_broker(exchange=s.EXCHANGE, mode=s.MODE, settings=s)

    # ---- Regime (по флагу) ----
    regime_enabled = bool(getattr(s, "REGIME_ENABLED", False))
    regime = None
    broker: BrokerPort = base_broker
    if regime_enabled:
        dxy_url = str(getattr(s, "DXY_API_URL", "") or "")
        btc_url = str(getattr(s, "BTC_DOM_API_URL", "") or "")
        fomc_url = str(getattr(s, "FOMC_API_URL", "") or "")
        dxy = DxyHttp(dxy_url) if dxy_url else None
        btd = BtcDominanceHttp(btc_url) if btc_url else None  # Исправлено имя
        fomc = FomcHttp(fomc_url) if fomc_url else None
        regime = RegimeDetector(dxy=dxy, btc_dom=btd, fomc=fomc, cfg=RegimeConfig())
        broker = GatedBroker(inner=base_broker, regime=regime, allow_sells_when_off=True)

    risk = RiskManager(RiskConfig.from_settings(s))
    exits = ProtectiveExits(storage=st, broker=broker, bus=bus, settings=s)
    health = HealthChecker(storage=st, broker=broker, bus=bus, settings=s)

    symbols: list[str] = [canonical(x.strip()) for x in (s.SYMBOLS or "").split(",") if x.strip()] or [canonical(s.SYMBOL)]
    orchs: dict[str, Orchestrator] = {}

    def _make_dms(sym: str) -> SafetySwitchPort:
        dms_bus = None
        if hasattr(bus, "__class__") and bus.__class__.__name__ == "AsyncEventBus":
            dms_bus = bus
        return DeadMansSwitch(
            storage=st,
            broker=broker,
            symbol=sym,
            timeout_ms=int(getattr(s, "DMS_TIMEOUT_MS", 120_000) or 120_000),
            rechecks=int(getattr(s, "DMS_RECHECKS", 2) or 2),
            recheck_delay_sec=float(getattr(s, "DMS_RECHECK_DELAY_SEC", 3.0) or 3.0),
            max_impact_pct=dec(str(getattr(s, "DMS_MAX_IMPACT_PCT", 0) or 0)),
            bus=dms_bus,
        )

    for sym in symbols:
        orchs[sym] = Orchestrator(
            symbol=sym,
            storage=st,
            broker=broker,
            bus=bus,
            risk=risk,
            exits=exits,
            health=health,
            settings=s,
            dms=_make_dms(sym),
            # Если потом расширим сигнатуру Оркестратора на regime=..., здесь будет готов флаг.
        )

    attach_alerts(bus, s)

    # Хинты для exits:
    if hasattr(exits, "on_hint") and hasattr(bus, "on"):
        bus.on("exits.hint", exits.on_hint)  # type: ignore[arg-type]

    tg_task: asyncio.Task | None = None
    if getattr(s, "TELEGRAM_BOT_COMMANDS_ENABLED", False) and getattr(s, "TELEGRAM_BOT_TOKEN", ""):
        raw_users = str(getattr(s, "TELEGRAM_ALLOWED_USERS", "") or "").strip()
        users: list[int] = []
        if raw_users:
            try:
                users = [int(x.strip()) for x in raw_users.split(",") if x.strip()]
            except Exception:
                _log.error("telegram_allowed_users_parse_failed", extra={"raw": raw_users}, exc_info=True)
        container_view = type("C", (), {
            "storage": st, "broker": broker, "risk": risk, "exits": exits, "orchestrators": orchs, "health": health, "regime": regime
        })()
        bot = TelegramBotCommands(
            bot_token=s.TELEGRAM_BOT_TOKEN,
            allowed_users=users,
            container=container_view,
            default_symbol=symbols[0],
        )
        tg_task = asyncio.create_task(bot.run())
        _log.info("telegram_bot_enabled")

    return Container(settings=s, storage=st, broker=broker, bus=bus, risk=risk, exits=exits, health=health, orchestrators=orchs, tg_bot_task=tg_task)
