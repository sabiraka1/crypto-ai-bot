from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Callable

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
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.http_client import create_http_client

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: IBroker
    bus: AsyncEventBus
    health: HealthChecker
    risk: RiskManager
    exits: ProtectiveExits
    orchestrator: Orchestrator
    lock: Optional[InstanceLock] = None


async def _telegram_send(settings: Any, text: str) -> None:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "") or ""
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    client = create_http_client(timeout_sec=10)
    try:
        await client.post(url, json=payload)
    except Exception as exc:
        _log.warning("telegram_send_failed", extra={"error": str(exc)})
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            await close()  # type: ignore[misc]


def _fmt_kv(d: dict) -> str:
    parts = []
    for k, v in d.items():
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return ", ".join(parts)


def attach_alerts(bus: AsyncEventBus, settings: Any) -> None:
    async def on_completed(evt: dict) -> None:
        text = "✅ <b>TRADE COMPLETED</b>\n" + _fmt_kv(evt)
        await _telegram_send(settings, text)

    async def on_blocked(evt: dict) -> None:
        text = "⛔️ <b>TRADE BLOCKED</b>\n" + _fmt_kv(evt)
        await _telegram_send(settings, text)

    async def on_failed(evt: dict) -> None:
        text = "❌ <b>TRADE FAILED</b>\n" + _fmt_kv(evt)
        await _telegram_send(settings, text)

    async def on_heartbeat(evt: dict) -> None:
        ok = "OK" if evt.get("ok") else "WARN"
        text = f"💓 <b>HEARTBEAT</b> {ok}\n" + _fmt_kv(evt)
        await _telegram_send(settings, text)

    bus.subscribe("trade.completed", on_completed)
    bus.subscribe("trade.blocked", on_blocked)
    bus.subscribe("trade.failed", on_failed)
    bus.subscribe("watchdog.heartbeat", on_heartbeat)

    _log.info(
        "telegram_alerts_attached",
        extra={
            "enabled": bool(
                getattr(settings, "TELEGRAM_BOT_TOKEN", "")
                and getattr(settings, "TELEGRAM_CHAT_ID", "")
            )
        },
    )


def _create_storage_for_mode(settings: Settings) -> Storage:
    db_path = settings.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=True, backup_retention_days=settings.BACKUP_RETENTION_DAYS)
    storage = Storage.from_connection(conn)
    _log.info("storage_created", extra={"mode": settings.MODE, "db_path": db_path})
    return storage


def _create_paper_price_feed(settings: Settings) -> Callable[[], Decimal]:
    """
    Возвращает синхронный callable для PaperBroker.price_feed:
      - PRICE_FEED=fixed → константа из FIXED_PRICE
      - PRICE_FEED=live  → фон-обновление через CcxtBroker(dry_run=True), чтение последней цены синхронно
    """
    if (settings.PRICE_FEED or "").lower() == "fixed":
        fixed = dec(str(settings.FIXED_PRICE))
        return lambda: fixed

    # live
    last: Decimal = dec("100")

    async def _updater() -> None:
        nonlocal last
        br = CcxtBroker(
            exchange_id=settings.EXCHANGE,
            enable_rate_limit=True,
            sandbox=bool(settings.SANDBOX),
            dry_run=True,  # только котировки
        )
        while True:
            try:
                t = await br.fetch_ticker(settings.SYMBOL)
                if t.last and t.last > 0:
                    last = t.last
            except Exception as exc:
                _log.warning("price_feed_update_failed", extra={"error": str(exc)})
            await asyncio.sleep(2)

    # стартуем таск обновления, вернем синхронный accessor
    try:
        asyncio.get_running_loop().create_task(_updater())
    except RuntimeError:
        # если цикла нет (редкий случай), создадим позже в первом заходе
        async def _delayed():
            await asyncio.sleep(0)
            await _updater()
        asyncio.get_event_loop().create_task(_delayed())  # type: ignore

    def _get() -> Decimal:
        return last

    return _get


def _create_broker_for_mode(settings: Settings) -> IBroker:
    mode = (settings.MODE or "").lower()
    if mode == "paper":
        balances = {"USDT": dec("10000")}
        price_feed = _create_paper_price_feed(settings)
        return PaperBroker(symbol=settings.SYMBOL, balances=balances, price_feed=price_feed)
    if mode == "live":
        if not settings.API_KEY or not settings.API_SECRET:
            raise ValueError("API creds required in live mode")
        return CcxtBroker(
            exchange_id=settings.EXCHANGE,
            api_key=settings.API_KEY,
            api_secret=settings.API_SECRET,
            enable_rate_limit=True,
            sandbox=bool(settings.SANDBOX),
            dry_run=False,
        )
    raise ValueError(f"Unknown MODE={settings.MODE}")


def build_container() -> Container:
    settings = Settings.load()
    storage = _create_storage_for_mode(settings)
    bus = AsyncEventBus(max_attempts=3, backoff_base_ms=250, backoff_factor=2.0)
    bus.attach_logger_dlq()

    attach_alerts(bus, settings)

    broker = _create_broker_for_mode(settings)

    risk = RiskManager(
        config=RiskConfig(
            cooldown_sec=settings.RISK_COOLDOWN_SEC,
            max_spread_pct=settings.RISK_MAX_SPREAD_PCT,
            max_position_base=settings.RISK_MAX_POSITION_BASE,
            max_orders_per_hour=settings.RISK_MAX_ORDERS_PER_HOUR,
            daily_loss_limit_quote=settings.RISK_DAILY_LOSS_LIMIT_QUOTE,
            max_fee_pct=settings.RISK_MAX_FEE_PCT,
            max_slippage_pct=settings.RISK_MAX_SLIPPAGE_PCT,
        ),
    )

    exits = ProtectiveExits(storage=storage, bus=bus, broker=broker, settings=settings)
    health = HealthChecker(storage=storage, broker=broker, bus=bus)

    lock: Optional[InstanceLock] = None
    if settings.MODE.lower() == "live":
        lock_owner = settings.POD_NAME or settings.HOSTNAME or "local"
        lock = InstanceLock(storage.conn, app="trader", owner=lock_owner)
        ok = False
        try:
            ok = lock.acquire(ttl_sec=300)
        except Exception as exc:
            _log.error("lock_init_failed", extra={"error": str(exc)})
            raise
        if not ok:
            raise RuntimeError("Another instance is already running (instance lock not acquired)")

    orchestrator = Orchestrator(
        symbol=settings.SYMBOL,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        health=health,
        settings=settings,
    )

    return Container(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        health=health,
        risk=risk,
        exits=exits,
        orchestrator=orchestrator,
        lock=lock,
    )
