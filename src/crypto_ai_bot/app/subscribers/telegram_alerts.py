from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("subscribers.telegram")


def attach_alerts(bus: Any, settings: Any) -> None:
    """
    сѸ Telegram: сѰ сѸя  EventBus  ѿѰя  Telegram.
    Ѹ ѾсѾ  сѹ: ѾѺ ѵс, HTML,  ѲсѲѵѽ .
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
        except Exception:  # noqa: BLE001
            _log.error("telegram_send_exception", exc_info=True)

    def _sub(topic: str, coro: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        for attr in ("subscribe", "on"):
            if hasattr(bus, attr):
                try:
                    getattr(bus, attr)(topic, coro)
                    return  # noqa: TRY300
                except Exception:  # noqa: BLE001
                    _log.error("bus_subscribe_failed", extra={"topic": topic}, exc_info=True)
        _log.error("bus_has_no_subscribe_api")

    # ====== Handlers ======

    async def on_auto_paused(evt: dict[str, Any]) -> None:
        inc("orchestrator_auto_paused_total", symbol=evt.get("symbol", ""))
        await _send(f"️ <b>AUTO-PAUSE</b> {evt.get('symbol', '')}\nѸѸ: <code>{evt.get('reason', '')}</code>")

    async def on_auto_resumed(evt: dict[str, Any]) -> None:
        inc("orchestrator_auto_resumed_total", symbol=evt.get("symbol", ""))
        await _send(f" <b>AUTO-RESUME</b> {evt.get('symbol', '')}\nѸѸ: <code>{evt.get('reason', '')}</code>")

    async def on_pos_mm(evt: dict[str, Any]) -> None:
        inc("reconcile_position_mismatch_total", symbol=evt.get("symbol", ""))
        await _send(
            " <b>RECONCILE</b> {s}\nѶ: <code>{b}</code>\nѽ: <code>{l}</code>".format(
                s=evt.get("symbol", ""), b=evt.get("exchange", ""), l=evt.get("local", "")
            )
        )

    async def on_dms_triggered(evt: dict[str, Any]) -> None:
        inc("dms_triggered_total", symbol=evt.get("symbol", ""))
        await _send(
            f" <b>DMS TRIGGERED</b> {evt.get('symbol', '')}\nѾ : <code>{evt.get('amount', '')}</code>"
        )

    async def on_dms_skipped(evt: dict[str, Any]) -> None:
        inc("dms_skipped_total", symbol=evt.get("symbol", ""))
        await _send(f" <b>DMS SKIPPED</b> {evt.get('symbol', '')}\n: <code>{evt.get('drop_pct', '')}%</code>")

    async def on_trade_completed(evt: dict[str, Any]) -> None:
        inc("trade_completed_total", symbol=evt.get("symbol", ""), side=evt.get("side", ""))
        s = evt.get("symbol", "")
        side = evt.get("side", "")
        cost = evt.get("cost", "")
        fee = evt.get("fee_quote", "")
        price = evt.get("price", "")
        amt = evt.get("amount", "")
        await _send(
            f" <b>TRADE</b> {s} {side.upper()}\nAmt: <code>{amt}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>"
        )

    async def on_trade_failed(evt: dict[str, Any]) -> None:
        inc("trade_failed_total", symbol=evt.get("symbol", ""), reason=evt.get("error", ""))
        await _send(f" <b>TRADE FAILED</b> {evt.get('symbol', '')}\n<code>{evt.get('error', '')}</code>")

    async def on_settled(evt: dict[str, Any]) -> None:
        inc("trade_settled_total", symbol=evt.get("symbol", ""), side=evt.get("side", ""))
        await _send(
            f" <b>SETTLED</b> {evt.get('symbol', '')} {evt.get('side', '').upper()} id=<code>{evt.get('order_id', '')}</code>"
        )

    async def on_settlement_timeout(evt: dict[str, Any]) -> None:
        inc("trade_settlement_timeout_total", symbol=evt.get("symbol", ""))
        await _send(
            f"⏱️ <b>SETTLEMENT TIMEOUT</b> {evt.get('symbol', '')} id=<code>{evt.get('order_id', '')}</code>"
        )

    async def on_budget_exceeded(evt: dict[str, Any]) -> None:
        inc("budget_exceeded_total", symbol=evt.get("symbol", ""), type=evt.get("type", ""))
        s = evt.get("symbol", "")
        kind = evt.get("type", "")
        detail = (
            f"count_5m={evt.get('count_5m', '')}/{evt.get('limit', '')}"
            if kind == "max_orders_5m"
            else f"turnover={evt.get('turnover', '')}/{evt.get('limit', '')}"
        )
        await _send(f"⏳ <b>BUDGET</b> {s} ѵѵ ({kind})\n{detail}")

    async def on_trade_blocked(evt: dict[str, Any]) -> None:
        inc("trade_blocked_total", symbol=evt.get("symbol", ""), reason=evt.get("reason", ""))
        await _send(f" <b>BLOCKED</b> {evt.get('symbol', '')}\nѸѸ: <code>{evt.get('reason', '')}</code>")

    async def on_broker_error(evt: dict[str, Any]) -> None:
        inc("broker_error_total", symbol=evt.get("symbol", ""))
        await _send(f" <b>BROKER ERROR</b> {evt.get('symbol', '')}\n<code>{evt.get('error', '')}</code>")

    async def on_health_report(evt: dict[str, Any]) -> None:
        if evt.get("ok", True):
            return
        parts = []
        for k in ("db", "bus", "broker"):
            v = evt.get(k)
            if v and v != "ok":
                parts.append(f"{k}={v}")
        summary = ", ".join(parts) or "degraded"
        await _send(f" <b>HEALTH FAIL</b>\n<code>{summary}</code>")

    async def on_alertmanager(evt: dict[str, Any]) -> None:
        p = evt.get("payload", {}) or {}
        status = p.get("status", "?")
        alerts = p.get("alerts", []) or []
        lines = [f"*Alertmanager* status: `{status}`", f"count: {len(alerts)}"]
        for a in alerts[:5]:
            ann = a.get("annotations", {}) or {}
            lbl = a.get("labels", {}) or {}
            name = lbl.get("alertname") or "Alert"
            text = ann.get("summary") or ann.get("description") or ""
            lines.append(f"- `{name}` {text}")
        await _send("\n".join(lines))

    for topic, handler in [
        (EVT.ORCH_AUTO_PAUSED, on_auto_paused),
        (EVT.ORCH_AUTO_RESUMED, on_auto_resumed),
        (EVT.RECONCILE_POSITION_MISMATCH, on_pos_mm),
        (EVT.DMS_TRIGGERED, on_dms_triggered),
        (EVT.DMS_SKIPPED, on_dms_skipped),
        (EVT.TRADE_COMPLETED, on_trade_completed),
        (EVT.TRADE_FAILED, on_trade_failed),
        (EVT.TRADE_SETTLED, on_settled),
        (EVT.TRADE_SETTLEMENT_TIMEOUT, on_settlement_timeout),
        (EVT.BUDGET_EXCEEDED, on_budget_exceeded),
        (EVT.TRADE_BLOCKED, on_trade_blocked),
        (EVT.BROKER_ERROR, on_broker_error),
        (EVT.HEALTH_REPORT, on_health_report),
        (EVT.ALERTS_ALERTMANAGER, on_alertmanager),
    ]:
        _sub(topic, handler)

    _log.info("telegram_alerts_enabled")
