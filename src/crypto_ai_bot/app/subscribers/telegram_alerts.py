from __future__ import annotations

from typing import Any

from crypto_ai_bot.app.telegram import TelegramAlerts
from crypto_ai_bot.core.application import events_topics
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("subscribers.telegram")

# Localization messages
MESSAGES = {
    "en": {
        "orch_paused": "Auto trading has been *paused* for {symbol}. Reason: {reason}",
        "orch_resumed": "Auto trading has been *resumed* for {symbol}.",
        "trade_ok": "✅ Trade completed for {symbol}: {side} {quote} {quote_ccy}",
        "trade_fail": "❌ Trade failed for {symbol}. Reason: {reason}",
        "risk_blocked": "⛔ Trade blocked by risk rule: {rule}",
        "budget_exceeded": "⛔ Budget exceeded. Daily PnL: {pnl} {ccy}",
        "broker_error": "⚠️ Broker error: {msg}",
        "health": "❤️ Health: price={price} spread={spread} spread%={spread_pct}",
        "dms_triggered": "🛑 DMS TRIGGERED for {symbol}. Prev={prev}, Last={last}",
        "dms_skipped": "ℹ️ DMS skipped for {symbol}. Prev={prev}, Last={last}",
        "alerts_forwarded": "📣 Alert forwarded: {labels}",
    },
}


def get_message(lang: str, key: str, **kwargs: str) -> str:
    """Get localized message."""
    lang = (lang or "en").lower()
    messages = MESSAGES.get(lang, MESSAGES["en"])
    template = messages.get(key, MESSAGES["en"].get(key, key))
    return template.format(**kwargs)


class AlertHandler:
    """Handler for telegram alerts."""

    def __init__(self, telegram: TelegramAlerts, settings: Any):
        self.telegram = telegram
        self.settings = settings
        self.lang = str(getattr(settings, "LANG", "en")).lower()

    async def send_text(self, text: str) -> None:
        """Send text message."""
        try:
            await self.telegram.send_text(text)
            inc("telegram.send_text.ok")
        except Exception:
            inc("telegram.send_text.err")
            _log.exception("telegram_send_text_failed")

    async def send_alert(self, text: str, labels: dict[str, str] | None = None) -> None:
        """Send alert with optional labels."""
        try:
            await self.telegram.send_text(text)
            if labels:
                await self.telegram.send_text(f"Labels: {labels}")
            inc("telegram.alert.ok")
        except Exception:
            inc("telegram.alert.err")
            _log.exception("telegram_alert_failed")

    async def on_orch_paused(self, payload: dict[str, Any]) -> None:
        """Handle orchestrator paused event."""
        text = get_message(
            self.lang, "orch_paused", symbol=payload.get("symbol", "?"), reason=payload.get("reason", "n/a")
        )
        await self.send_text(text)

    async def on_orch_resumed(self, payload: dict[str, Any]) -> None:
        """Handle orchestrator resumed event."""
        text = get_message(self.lang, "orch_resumed", symbol=payload.get("symbol", "?"))
        await self.send_text(text)

    async def on_trade_completed(self, payload: dict[str, Any]) -> None:
        """Handle trade completed event."""
        text = get_message(
            self.lang,
            "trade_ok",
            symbol=payload.get("symbol", "?"),
            side=payload.get("side", "?"),
            quote=str(payload.get("quote", "0")),
            quote_ccy=payload.get("quote_ccy", ""),
        )
        await self.send_text(text)

    async def on_trade_failed(self, payload: dict[str, Any]) -> None:
        """Handle trade failed event."""
        text = get_message(
            self.lang,
            "trade_fail",
            symbol=payload.get("symbol", "?"),
            reason=payload.get("reason", "unknown"),
        )
        await self.send_text(text)

    async def on_risk_blocked(self, payload: dict[str, Any]) -> None:
        """Handle risk blocked event."""
        text = get_message(self.lang, "risk_blocked", rule=payload.get("rule", "unknown"))
        await self.send_text(text)

    async def on_budget_exceeded(self, payload: dict[str, Any]) -> None:
        """Handle budget exceeded event."""
        text = get_message(
            self.lang,
            "budget_exceeded",
            pnl=str(payload.get("pnl", "0")),
            ccy=payload.get("ccy", ""),
        )
        await self.send_text(text)

    async def on_broker_error(self, payload: dict[str, Any]) -> None:
        """Handle broker error event."""
        text = get_message(self.lang, "broker_error", msg=payload.get("message", "unknown"))
        await self.send_text(text)

    async def on_health(self, payload: dict[str, Any]) -> None:
        """Handle health report event."""
        text = get_message(
            self.lang,
            "health",
            price=str(payload.get("price", "?")),
            spread=str(payload.get("spread", "?")),
            spread_pct=str(payload.get("spread_pct", "?")),
        )
        await self.send_text(text)

    async def on_dms_triggered(self, payload: dict[str, Any]) -> None:
        """Handle DMS triggered event."""
        text = get_message(
            self.lang,
            "dms_triggered",
            symbol=payload.get("symbol", "?"),
            prev=str(payload.get("prev", "?")),
            last=str(payload.get("last", "?")),
        )
        await self.send_text(text)

    async def on_dms_skipped(self, payload: dict[str, Any]) -> None:
        """Handle DMS skipped event."""
        text = get_message(
            self.lang,
            "dms_skipped",
            symbol=payload.get("symbol", "?"),
            prev=str(payload.get("prev", "?")),
            last=str(payload.get("last", "?")),
        )
        await self.send_text(text)

    async def on_alertmanager(self, payload: dict[str, Any]) -> None:
        """Handle alertmanager event."""
        labels = payload.get("labels", {})
        text = get_message(self.lang, "alerts_forwarded", labels=str(labels))
        await self.send_alert(text, labels=labels)


def attach_alerts(bus: Any, settings: Any) -> None:
    """Subscribe to bus events and forward to Telegram."""
    telegram = TelegramAlerts(settings=settings)
    handler = AlertHandler(telegram, settings)

    # Subscribe to events
    bus.on(events_topics.ORCH_AUTO_PAUSED, handler.on_orch_paused)
    bus.on(events_topics.ORCH_AUTO_RESUMED, handler.on_orch_resumed)
    bus.on(events_topics.TRADE_COMPLETED, handler.on_trade_completed)
    bus.on(events_topics.TRADE_FAILED, handler.on_trade_failed)
    bus.on(events_topics.RISK_BLOCKED, handler.on_risk_blocked)
    bus.on(events_topics.BUDGET_EXCEEDED, handler.on_budget_exceeded)
    bus.on(events_topics.BROKER_ERROR, handler.on_broker_error)
    bus.on(events_topics.HEALTH_REPORT, handler.on_health)
    bus.on(events_topics.DMS_TRIGGERED, handler.on_dms_triggered)
    bus.on(events_topics.DMS_SKIPPED, handler.on_dms_skipped)
    bus.on(events_topics.ALERTS_ALERTMANAGER, handler.on_alertmanager)
