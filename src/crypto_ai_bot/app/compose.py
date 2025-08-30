from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Dict, List

from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.infrastructure.safety.instance_lock import InstanceLock
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator
    orchestrators: Dict[str, Orchestrator]
    broker: IBroker
    lock: Optional[InstanceLock] = None


# ---------- Telegram helpers ----------
async def _telegram_send(settings: Any, text: str) -> None:
    token = (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = (getattr(settings, "TELEGRAM_CHAT_ID", "") or "").strip()
    if not token or not chat_id:
        return
    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=5.0) as cli:
            await cli.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception:
        pass


def _fmt_kv(d: dict) -> str:
    try:
        return "\n".join(f"{k}={v}" for k, v in d.items())
    except Exception:
        return str(d)


# ---------- Alerts wiring ----------
def attach_alerts(bus: AsyncEventBus, settings: Any) -> None:
    async def on_completed(evt: dict) -> None:
        await _telegram_send(settings, "✅ <b>TRADE COMPLETED</b>\n" + _fmt_kv(evt))
    async def on_blocked(evt: dict) -> None:
        await _telegram_send(settings, "⛔️ <b>TRADE BLOCKED</b>\n" + _fmt_kv(evt))
    async def on_failed(evt: dict) -> None:
        await _telegram_send(settings, "❌ <b>TRADE FAILED</b>\n" + _fmt_kv(evt))
    async def on_heartbeat(evt: dict) -> None:
        ok = "OK" if evt.get("ok") else "WARN"
        await _telegram_send(settings, f"💓 <b>HEARTBEAT</b> {ok}\n" + _fmt_kv(evt))
    async def on_position_mismatch(evt: dict) -> None:
        sym = evt.get("symbol", ""); local = evt.get("local", ""); exch = evt.get("exchange", "")
        await _telegram_send(settings, "⚠️ <b>POSITION MISMATCH</b>\n"
                           f"symbol={sym}\nlocal_base={local}\nexchange_base={exch}")
    async def on_paused(evt: dict) -> None:
        await _telegram_send(settings, "⏸️ <b>ORCHESTRATOR PAUSED</b>\n" + _fmt_kv(evt))
    async def on_resumed(evt: dict) -> None:
        await _telegram_send(settings, "▶️ <b>ORCHESTRATOR RESUMED</b>\n" + _fmt_kv(evt))
    async def on_auto_paused(evt: dict) -> None:
        await _telegram_send(settings, "🛑 <b>AUTO-PAUSED (SLA/BUDGET)</b>\n" + _fmt_kv(evt))
    async def on_auto_resumed(evt: dict) -> None:
        await _telegram_send(settings, "🟢 <b>AUTO-RESUMED</b>\n" + _fmt_kv(evt))

    bus.subscribe("trade.completed", on_completed)
    bus.subscribe("trade.blocked", on_blocked)
    bus.subscribe("trade.failed", on_failed)
    bus.subscribe("watchdog.heartbeat", on_heartbeat)
    bus.subscribe("reconcile.position_mismatch", on_position_mismatch)
    bus.subscribe("orchestrator.paused", on_paused)
    bus.subscribe("orchestrator.resumed", on_resumed)
    bus.subscribe("orchestrator.auto_paused", on_auto_paused)
    bus.subscribe("orchestrator.auto_resumed", on_auto_resumed)

    _log.info("telegram_alerts_attached",
              extra={"enabled": bool(getattr(settings, "TELEGRAM_BOT_TOKEN", "") and getattr(settings, "TELEGRAM_CHAT_ID", ""))})


# ---------- Storage / Brokers ----------
def _open_storage(settings: Settings) -> Storage:
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(os.path.join(settings.DATA_DIR, "bot.db"))
    conn.row_factory = sqlite3.Row
    run_migrations(conn)  # индексы теперь создаёт миграция 006
    return Storage(conn)

    # UNIQUE client_order_id (для дедупликации) + полезные индексы
    try:
        conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_client_id_unique '
            'ON trades(client_order_id) '
            'WHERE client_order_id IS NOT NULL AND client_order_id <> "";'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_trades_broker_order_id '
            'ON trades(broker_order_id);'
        )
        conn.commit()
    except Exception:
        pass

    return Storage(conn)


def _create_broker_live(settings: Settings) -> IBroker:
    wait_close = float(getattr(settings, "WAIT_ORDER_CLOSE_SEC", 0.0) or 0.0)
    rate_cps  = float(getattr(settings, "RATE_CALLS_PER_SEC", 0.0) or 0.0)
    rate_burst = int(getattr(settings, "RATE_BURST", 0) or 0)
    idem_bucket = int(getattr(settings, "IDEMPOTENCY_BUCKET_MS", 60_000) or 60_000)
    if not settings.API_KEY or not settings.API_SECRET:
        raise ValueError("API creds required in live mode")
    return CcxtBroker(
        exchange_id=settings.EXCHANGE,
        api_key=settings.API_KEY,
        api_secret=settings.API_SECRET,
        enable_rate_limit=True,
        sandbox=bool(settings.SANDBOX),
        dry_run=False,
        wait_close_sec=wait_close,
        rate_calls_per_sec=rate_cps,
        rate_burst=rate_burst,
        idempotency_bucket_ms=idem_bucket,
    )


def _make_simple_price_feed(symbol: str):
    base_price = dec("100")
    async def _feed():
        return base_price, base_price - dec("0.1"), base_price + dec("0.1")
    return _feed


def _create_broker_paper(settings: Settings, symbol: str) -> IBroker:
    balances = {"USDT": dec("10000")}
    price_feed = _make_simple_price_feed(symbol)
    return PaperBroker(symbol=symbol, balances=balances, price_feed=price_feed)


# ---------- Container builder (multi-symbol) ----------
def build_container() -> Container:
    settings = Settings.load()
    storage = _open_storage(settings)
    bus = AsyncEventBus()
    attach_alerts(bus, settings)
    health = HealthChecker(storage=storage)
    risk = RiskManager(RiskConfig.from_settings(settings))
    exits = ProtectiveExits(storage=storage, broker=None, settings=settings)  # broker проставим ниже

    syms: List[str] = [settings.SYMBOL]
    extra = [s.strip() for s in str(getattr(settings, "SYMBOLS", "") or "").split(",") if s.strip()]
    for s in extra:
        if s not in syms:
            syms.append(s)

    orchestrators: Dict[str, Orchestrator] = {}
    mode = (settings.MODE or "").lower()
    primary_broker: Optional[IBroker] = None

    if mode == "live":
        primary_broker = _create_broker_live(settings)
        for sym in syms:
            exits_sym = ProtectiveExits(storage=storage, broker=primary_broker, settings=settings)
            orch = Orchestrator(symbol=sym, storage=storage, broker=primary_broker, bus=bus,
                                risk=risk, exits=exits_sym, health=health, settings=settings)
            orchestrators[sym] = orch
    elif mode == "paper":
        for sym in syms:
            pb = _create_broker_paper(settings, sym)
            exits_sym = ProtectiveExits(storage=storage, broker=pb, settings=settings)
            orch = Orchestrator(symbol=sym, storage=storage, broker=pb, bus=bus,
                                risk=risk, exits=exits_sym, health=health, settings=settings)
            orchestrators[sym] = orch
        primary_broker = orchestrators[settings.SYMBOL].broker
    else:
        raise ValueError(f"Unknown MODE={settings.MODE}")

    lock = InstanceLock(settings.INSTANCE_LOCK_FILE)
    if not lock.acquire(block=False):
        raise RuntimeError("Another instance is running")

    return Container(
        settings=settings,
        storage=storage,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orchestrators[settings.SYMBOL],
        orchestrators=orchestrators,
        broker=primary_broker,
        lock=lock,
    )
