from __future__ import annotations

from typing import Any, Callable, Awaitable

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("subscribers.telegram")


def attach_alerts(bus: Any, settings: Any) -> None:
    """
    Регистрирует Telegram-уведомления на события из EventBus.
    Ничего не меняет в логике — это ровно та же проводка, которая была в compose.attach_alerts.
    """
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

    # ======= Обработчики алертов =======
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
