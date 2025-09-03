from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("subscribers.telegram")



# --- Localization ---
def _t(lang: str, key: str, **kw: str) -> str:
    L = {
        "en": {
            "ORCH_PAUSED": "⏸️ <b>PAUSED</b> {symbol} (auto)",
            "ORCH_RESUMED": "▶️ <b>RESUMED</b> {symbol} (auto)",
            "DMS_TRIGGERED": "🛑 <b>DMS</b> {symbol}\nDrop: <code>{drop_pct}%</code>",
            "DMS_SKIPPED": "ℹ️ <b>DMS SKIPPED</b> {symbol}",
            "TRADE_COMPLETED": "💹 <b>TRADE</b> {symbol} {side}\nAmt: <code>{amount}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>",
            "TRADE_FAILED": "❌ <b>TRADE FAILED</b> {symbol}\n<code>{error}</code>",
            "TRADE_SETTLED": "✅ <b>SETTLED</b> {symbol} {side} id=<code>{order_id}</code>",
            "SETTLEMENT_TIMEOUT": "⏱️ <b>SETTLEMENT TIMEOUT</b> {symbol} id=<code>{order_id}</code>",
            "BUDGET_BLOCK": "⏳ <b>RISK/BUDGET BLOCK</b> {symbol}\n{detail}",
            "RISK_BLOCKED": "⛔ <b>RISK/BLOCKED</b> {symbol}\nReason: <code>{reason}</code>",
            "BROKER_ERROR": "⚠️ <b>BROKER ERROR</b> {symbol}\n<code>{error}</code>",
            "HEALTH_FAIL": "🩻 <b>HEALTH FAIL</b>\n<code>{summary}</code>",
        },
        "ru": {
            "ORCH_PAUSED": "⏸️ <b>ПАУЗА</b> {symbol} (авто)",
            "ORCH_RESUMED": "▶️ <b>ВОЗОБНОВЛЕНО</b> {symbol} (авто)",
            "DMS_TRIGGERED": "🛑 <b>DMS</b> {symbol}\nПадение: <code>{drop_pct}%</code>",
            "DMS_SKIPPED": "ℹ️ <b>DMS ПРОПУЩЕН</b> {symbol}",
            "TRADE_COMPLETED": "💹 <b>СДЕЛКА</b> {symbol} {side}\nКол-во: <code>{amount}</code> @ <code>{price}</code>\nСтоимость: <code>{cost}</code> Комиссия: <code>{fee}</code>",
            "TRADE_FAILED": "❌ <b>ОШИБКА СДЕЛКИ</b> {symbol}\n<code>{error}</code>",
            "TRADE_SETTLED": "✅ <b>ЗАВЕРШЕНО</b> {symbol} {side} id=<code>{order_id}</code>",
            "SETTLEMENT_TIMEOUT": "⏱️ <b>ТАЙМАУТ ЗАВЕРШЕНИЯ</b> {symbol} id=<code>{order_id}</code>",
            "BUDGET_BLOCK": "⏳ <b>РИСК/БЮДЖЕТ БЛОК</b> {symbol}\n{detail}",
            "RISK_BLOCKED": "⛔ <b>РИСК/БЛОК</b> {symbol}\nПричина: <code>{reason}</code>",
            "BROKER_ERROR": "⚠️ <b>ОШИБКА БРОКЕРА</b> {symbol}\n<code>{error}</code>",
            "HEALTH_FAIL": "🩻 <b>НЕЗДОРОВО</b>\n<code>{summary}</code>",
        },
        "tr": {
            "ORCH_PAUSED": "⏸️ <b>DURAKLATILDI</b> {symbol} (otomatik)",
            "ORCH_RESUMED": "▶️ <b>DEVAM</b> {symbol} (otomatik)",
            "DMS_TRIGGERED": "🛑 <b>DMS</b> {symbol}\nDüşüş: <code>{drop_pct}%</code>",
            "DMS_SKIPPED": "ℹ️ <b>DMS ATLANDI</b> {symbol}",
            "TRADE_COMPLETED": "💹 <b>İŞLEM</b> {symbol} {side}\nMiktar: <code>{amount}</code> @ <code>{price}</code>\nTutar: <code>{cost}</code> Ücret: <code>{fee}</code>",
            "TRADE_FAILED": "❌ <b>İŞLEM HATASI</b> {symbol}\n<code>{error}</code>",
            "TRADE_SETTLED": "✅ <b>KAPANDI</b> {symbol} {side} id=<code>{order_id}</code>",
            "SETTLEMENT_TIMEOUT": "⏱️ <b>KAPANMA ZAMANI AŞIMI</b> {symbol} id=<code>{order_id}</code>",
            "BUDGET_BLOCK": "⏳ <b>RİSK/BÜTÇE ENGELİ</b> {symbol}\n{detail}",
            "RISK_BLOCKED": "⛔ <b>RİSK/ENGELLENDİ</b> {symbol}\nNeden: <code>{reason}</code>",
            "BROKER_ERROR": "⚠️ <b>ARACI HATASI</b> {symbol}\n<code>{error}</code>",
            "HEALTH_FAIL": "🩻 <b>SAĞLIK SORUNU</b>\n<code>{summary}</code>",
        },
    }
    lang = (lang or "en").lower()
    if lang not in L: lang = "en"
    tpl = L[lang].get(key, L["en"].get(key, key))
    return tpl.format(**kw)


def attach_alerts(bus: Any, settings: Any) -> None:
    """
    Subscribe EventBus alerts and forward to Telegram.
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
        await _send(f"️ <b>AUTO-PAUSE</b> {evt.get('symbol', '')}\nReason: <code>{evt.get('reason', '')}</code>")

    async def on_auto_resumed(evt: dict[str, Any]) -> None:
        inc("orchestrator_auto_resumed_total", symbol=evt.get("symbol", ""))
        await _send(f" <b>AUTO-RESUME</b> {evt.get('symbol', '')}\nReason: <code>{evt.get('reason', '')}</code>")

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
        await _send(_t(lang, 'DMS_TRIGGERED', symbol=evt.get('symbol',''), drop_pct=str(evt.get('drop_pct',''))))

    async def on_trade_completed(evt: dict[str, Any]) -> None:
        inc("trade_completed_total", symbol=evt.get("symbol", ""), side=evt.get("side", ""))
        s = evt.get("symbol", "")
        side = evt.get("side", "")
        cost = evt.get("cost", "")
        fee = evt.get("fee_quote", "")
        price = evt.get("price", "")
        amt = evt.get("amount", "")
        await _send(_t(lang, 'TRADE_COMPLETED', symbol=s, side=side.upper(), amount=str(amt), price=str(price), cost=str(cost), fee=str(fee)))}\nAmt: <code>{amt}</code> @ <code>{price}</code>\nCost: <code>{cost}</code> Fee: <code>{fee}</code>"
        )

    async def on_trade_failed(evt: dict[str, Any]) -> None:
        inc("trade_failed_total", symbol=evt.get("symbol", ""), reason=evt.get("error", ""))
        await _send(_t(lang, 'TRADE_FAILED', symbol=evt.get('symbol',''), error=str(evt.get('error',''))))

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
        await _send(_t(lang, 'BUDGET_BLOCK', symbol=s, detail=detail))

    async def on_trade_blocked(evt: dict[str, Any]) -> None:
        inc("trade_blocked_total", symbol=evt.get("symbol", ""), reason=evt.get("reason", ""))
        await _send(_t(lang, 'RISK_BLOCKED', symbol=evt.get('symbol',''), reason=str(evt.get('reason',''))))

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
        await _send(_t(lang, 'HEALTH_FAIL', summary=summary))

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
