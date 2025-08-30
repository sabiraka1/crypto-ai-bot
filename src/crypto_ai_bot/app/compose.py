from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List

from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.infrastructure.brokers.symbols import canonical
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.app.adapters.telegram import TelegramAlerts

_log = get_logger("compose")

@dataclass
class Container:
    settings: Settings
    storage: Storage
    broker
    bus: AsyncEventBus
    risk: RiskManager
    exits: ProtectiveExits
    health: HealthChecker
    orchestrators: Dict[str, Orchestrator]

def _open_storage(settings: Settings) -> Storage:
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(os.path.join(settings.DATA_DIR, "bot.db"))
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    return Storage(conn)

def attach_alerts(bus: AsyncEventBus, settings: Settings) -> None:
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
        try:
            bus.subscribe(topic, coro)  # type: ignore[attr-defined]
        except Exception:
            try:
                bus.on(topic, coro)      # type: ignore[attr-defined]
            except Exception as exc:
                _log.error("bus_subscribe_failed", extra={"topic": topic, "error": str(exc)})

    # уже были:
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

    # НОВОЕ: сделки / бюджет / блокировки
    async def on_trade_completed(evt: dict):
        s = evt.get("symbol",""); side = evt.get("side","")
        cost = evt.get("cost",""); fee = evt.get("fee_quote","")
        price = evt.get("price",""); amt = evt.get("amount","")
        await _send(f"✅ <b>TRADE</b> {s} {side.upper()}\nAmt: <code>{amt}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>")

    async def on_budget_exceeded(evt: dict):
        s = evt.get("symbol",""); kind = evt.get("type","")
        detail = f"count_5m={evt.get('count_5m','')}/{evt.get('limit','')}" if kind=="max_orders_5m" else f"turnover={evt.get('turnover','')}/{evt.get('limit','')}"
        await _send(f"⏳ <b>BUDGET</b> {s} превышен ({kind})\n{detail}")

    async def on_trade_blocked(evt: dict):
        s = evt.get("symbol",""); reason = evt.get("reason","")
        await _send(f"🚫 <b>BLOCKED</b> {s}\nПричина: <code>{reason}</code>")

    for t, h in [
        ("orchestrator.auto_paused", on_auto_paused),
        ("orchestrator.auto_resumed", on_auto_resumed),
        ("reconcile.position_mismatch", on_pos_mm),
        ("safety.dms.triggered", on_dms_triggered),
        ("safety.dms.skipped", on_dms_skipped),
        ("trade.completed", on_trade_completed),      # NEW
        ("budget.exceeded", on_budget_exceeded),      # NEW
        ("trade.blocked", on_trade_blocked),          # NEW
    ]:
        _sub(t, h)
    _log.info("telegram_alerts_enabled")

def build_container() -> Container:
    s = Settings.load()
    st = _open_storage(s)
    bus = AsyncEventBus()
    br = make_broker(exchange=s.EXCHANGE, mode=s.MODE, settings=s)
    risk = RiskManager(RiskConfig.from_settings(s))
    risk.attach_storage(st)
    risk.attach_settings(s)
    exits = ProtectiveExits(storage=st, broker=br, bus=bus, settings=s)
    health = HealthChecker(storage=st, broker=br, bus=bus, settings=s)

    symbols: List[str] = [canonical(x.strip()) for x in (s.SYMBOLS or "").split(",") if x.strip()] or [canonical(s.SYMBOL)]
    orchs: Dict[str, Orchestrator] = {}
    for sym in symbols:
        orchs[sym] = Orchestrator(
            symbol=sym, storage=st, broker=br, bus=bus,
            risk=risk, exits=exits, health=health, settings=s,
        )

    attach_alerts(bus, s)
    return Container(settings=s, storage=st, broker=br, bus=bus, risk=risk, exits=exits, health=health, orchestrators=orchs)
