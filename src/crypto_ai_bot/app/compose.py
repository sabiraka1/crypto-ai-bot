from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Any

from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.utils.symbols import canonical
from crypto_ai_bot.core.application.ports import SafetySwitchPort
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.utils.time import now_ms  # <— для миграций

_log = get_logger("compose")


@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker: Any
    bus: Any
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    orchestrators: Dict[str, Orchestrator]


def _open_storage(settings: Settings) -> Storage:
    # Путь БД берём из настроек; каталог создаём, если его нет
    db_path = settings.DB_PATH
    db_dir = os.path.dirname(db_path) or "."
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # PRAGMA частично применяются в раннере, но дополнительные здесь не мешают
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    # Важно: сигнатура runner требует now_ms и db_path
    run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=True,
                   backup_retention_days=int(getattr(settings, "BACKUP_RETENTION_DAYS", 30) or 30))
    return Storage(conn)


# --- Выбор типа Event Bus: Redis если URL задан, иначе in-memory ---
def _build_event_bus(settings: Settings) -> Any:
    redis_url = getattr(settings, "EVENT_BUS_URL", "") or ""
    if redis_url:
        bus = RedisEventBus(redis_url)
    else:
        bus = AsyncEventBus()
    return bus


def attach_alerts(bus: Any, settings: Settings) -> None:
    """Привязывает обработчики к событиям шины для отправки Telegram-уведомлений."""
    tg = TelegramAlerts(bot_token=getattr(settings, "TELEGRAM_BOT_TOKEN", ""),
                        chat_id=getattr(settings, "TELEGRAM_CHAT_ID", ""))
    if not tg.enabled():
        _log.info("telegram_alerts_disabled")
        return

    async def _send(text: str) -> None:
        try:
            ok = await tg.send(text)
            if not ok:
                _log.warning("telegram_send_not_ok")
        except Exception as exc:
            _log.error("telegram_send_exception", extra={"error": str(exc)})

    def _sub(topic: str, coro):
        # универсальная подписка (для AsyncEventBus или RedisEventBus)
        for attr in ("subscribe", "on"):
            if hasattr(bus, attr):
                try:
                    getattr(bus, attr)(topic, coro)
                    return
                except Exception as exc:
                    _log.error("bus_subscribe_failed", extra={"topic": topic, "error": str(exc)})
        _log.error("bus_has_no_subscribe_api")

    # Определяем обработчики для важных событий
    async def on_auto_paused(evt: dict):
        await _send(f"⚠️ <b>AUTO-PAUSE</b> {evt.get('symbol','')}\nПричина: <code>{evt.get('reason','')}</code>")

    async def on_auto_resumed(evt: dict):
        await _send(f"🟢 <b>AUTO-RESUME</b> {evt.get('symbol','')}\nПричина: <code>{evt.get('reason','')}</code>")

    async def on_pos_mm(evt: dict):
        await _send(f"🔄 <b>RECONCILE</b> {evt.get('symbol','')}\nБиржа: <code>{evt.get('exchange','')}</code>\nЛокально: <code>{evt.get('local','')}</code>")

    async def on_dms_triggered(evt: dict):
        await _send(f"🛑 <b>DMS TRIGGERED</b> {evt.get('symbol','')}\nПродано базового: <code>{evt.get('amount','')}</code>")

    async def on_dms_skipped(evt: dict):
        await _send(f"⛔ <b>DMS SKIPPED</b> {evt.get('symbol','')}\nПадение: <code>{evt.get('drop_pct','')}%</code>")

    async def on_trade_completed(evt: dict):
        s = evt.get("symbol",""); side = evt.get("side","")
        cost = evt.get("cost",""); fee = evt.get("fee_quote","")
        price = evt.get("price",""); amt = evt.get("amount","")
        await _send(f"✅ <b>TRADE</b> {s} {side.upper()}\nAmt: <code>{amt}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>")

    async def on_budget_exceeded(evt: dict):
        s = evt.get("symbol",""); kind = evt.get("type","")
        detail = f"count_5m={evt.get('count_5m','')}/{evt.get('limit','')}" if kind == "max_orders_5m" else f"turnover={evt.get('turnover','')}/{evt.get('limit','')}"
        await _send(f"⏳ <b>BUDGET</b> {s} превышен ({kind})\n{detail}")

    async def on_trade_blocked(evt: dict):
        s = evt.get("symbol",""); reason = evt.get("reason","")
        await _send(f"🚫 <b>BLOCKED</b> {s}\nПричина: <code>{reason}</code>")

    # Подписываемся на события через универсальную функцию _sub
    for topic, handler in [
        ("orchestrator.auto_paused", on_auto_paused),
        ("orchestrator.auto_resumed", on_auto_resumed),
        ("reconcile.position_mismatch", on_pos_mm),
        ("safety.dms.triggered", on_dms_triggered),
        ("safety.dms.skipped", on_dms_skipped),
        ("trade.completed", on_trade_completed),
        ("budget.exceeded", on_budget_exceeded),
        ("trade.blocked", on_trade_blocked),
    ]:
        _sub(topic, handler)

    _log.info("telegram_alerts_enabled")


async def build_container_async() -> Container:
    # Загружаем конфигурацию из переменных окружения/файла
    s = Settings.load()
    # Открываем или создаём (при отсутствии) хранилище данных
    st = _open_storage(s)
    # Инициируем шину событий
    bus = _build_event_bus(s)
    await bus.start() if hasattr(bus, "start") else None

    # Создаём адаптер к бирже (реальный или paper-симулятор в зависимости от режима)
    br = make_broker(exchange=s.EXCHANGE, mode=s.MODE, settings=s)
    # Инициируем риск-менеджер с конфигурацией лимитов (без прямого подключения к хранилищу)
    risk = RiskManager(RiskConfig.from_settings(s))
    # Создаём сервисы защитных выходов и мониторинга здоровья
    exits = ProtectiveExits(storage=st, broker=br, bus=bus, settings=s)
    health = HealthChecker(storage=st, broker=br, bus=bus, settings=s)

    # Поддержка множественных символов: список оркестраторов
    symbols: List[str] = [canonical(x.strip()) for x in (s.SYMBOLS or "").split(",") if x.strip()] or [canonical(s.SYMBOL)]
    orchs: Dict[str, Orchestrator] = {}

    def _make_dms(sym: str) -> SafetySwitchPort:
        # Фабричная функция для DeadMan'sSwitch под каждый символ
        return DeadMansSwitch(
            storage=st, broker=br, symbol=sym,
            timeout_ms=int(getattr(s, "DMS_TIMEOUT_MS", 120_000) or 120_000),
            rechecks=int(getattr(s, "DMS_RECHECKS", 2) or 2),
            recheck_delay_sec=float(getattr(s, "DMS_RECHECK_DELAY_SEC", 3.0) or 3.0),
            max_impact_pct=getattr(s, "DMS_MAX_IMPACT_PCT", 0),
            bus=bus,
        )

    # Инициализируем оркестраторы для каждого символа
    for sym in symbols:
        orchs[sym] = Orchestrator(
            symbol=sym, storage=st, broker=br, bus=bus,
            risk=risk, exits=exits, health=health, settings=s, dms=_make_dms(sym),
        )

    # Подключаем Telegram-алерты к событиям, если настроены токены
    attach_alerts(bus, s)
    return Container(settings=s, storage=st, broker=br, bus=bus, risk=risk, exits=exits, health=health, orchestrators=orchs)
