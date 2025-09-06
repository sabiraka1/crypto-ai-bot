"""Telegram alerts handler for event bus notifications.

Located in app layer - subscribes to events and sends Telegram notifications.
Routes critical events from the system to Telegram channel.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional, Protocol, Callable

from crypto_ai_bot.core.application.events_topics import EventTopics
from crypto_ai_bot.core.application.ports import NotificationPort
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger(__name__)


# ============== Localization ==============

MESSAGES = {
    "en": {
        # Orchestrator events
        "orch_started": "🚀 Trading started for {symbol}",
        "orch_stopped": "🛑 Trading stopped for {symbol}",
        "orch_paused": "⏸️ Trading paused for {symbol}\nReason: {reason}",
        "orch_resumed": "▶️ Trading resumed for {symbol}",

        # Trade events
        "trade_opened": "📈 Position opened: {symbol}\n{side} {amount:.4f} @ {price:.2f}",
        "trade_closed": "📊 Position closed: {symbol}\nPnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%)",
        "trade_failed": "❌ Trade failed: {symbol}\nReason: {reason}",

        # Risk events
        "risk_blocked": "🛡️ Trade blocked by risk rule\nRule: {rule}\nReason: {reason}",
        "risk_limit_hit": "⚠️ Risk limit reached\n{limit_type}: {current}/{max}",
        "stop_loss_triggered": "🔴 Stop loss triggered: {symbol}\nLoss: {loss:.2f} USDT",
        "take_profit_triggered": "🟢 Take profit triggered: {symbol}\nProfit: {profit:.2f} USDT",

        # System events
        "health_degraded": "⚠️ System health degraded\nComponent: {component}\nStatus: {status}",
        "health_restored": "✅ System health restored",
        "dms_triggered": "🚨 EMERGENCY: Dead Man's Switch triggered!\nSymbol: {symbol}\nAction: {action}",
        "broker_error": "❌ Broker error: {error}",

        # Market events
        "regime_changed": "🌍 Market regime changed\nFrom: {from_regime}\nTo: {to_regime}",
        "high_volatility": "📊 High volatility detected: {symbol}\nATR: {atr:.2f}",

        # Summary events
        "daily_summary": "📅 Daily Summary\nPnL: {pnl:+.2f} USDT\nTrades: {trades}\nWin rate: {win_rate:.1f}%",
    },

    "es": {
        "trade_opened": "📈 Posición abierta: {symbol}\n{side} {amount:.4f} @ {price:.2f}",
        "trade_closed": "📊 Posición cerrada: {symbol}\nPnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%)",
        # ... más traducciones
    }
}


def get_message(lang: str, key: str, **kwargs: Any) -> str:
    """Get localized message with formatting."""
    lang = (lang or "en").lower()
    messages = MESSAGES.get(lang, MESSAGES["en"])
    template = messages.get(key)

    if not template:
        # Fallback to English if key not found
        template = MESSAGES["en"].get(key, f"Unknown event: {key}")

    try:
        return template.format(**kwargs)
    except (KeyError, ValueError) as e:
        _log.warning("message_formatting_failed", extra={"key": key, "kwargs": kwargs, "error": str(e)})
        return template


# ============== Protocols ==============

class EventBusProtocol(Protocol):
    """Protocol for event bus interface."""

    def on(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> None: ...
    def on_wildcard(self, pattern: str, handler: Callable[[dict[str, Any]], Any]) -> None: ...


class TelegramClientProtocol(Protocol):
    """Protocol for Telegram client."""

    async def send_text(
        self,
        text: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False
    ) -> None: ...


# ============== Throttling ==============

class MessageThrottle:
    """Throttle messages to prevent spam."""

    def __init__(self, min_interval_sec: float = 1.0, burst_limit: int = 5):
        self.min_interval_sec = min_interval_sec
        self.burst_limit = burst_limit
        self._last_sent: float = 0.0
        self._burst_counter: int = 0
        self._burst_reset_time: float = 0.0

    def allow(self) -> bool:
        """Check if message can be sent."""
        now = time.time()

        # Reset burst counter after 1 minute
        if now - self._burst_reset_time > 60:
            self._burst_counter = 0
            self._burst_reset_time = now

        # Check burst limit
        if self._burst_counter >= self.burst_limit:
            return False

        # Check minimum interval
        if now - self._last_sent < self.min_interval_sec:
            return False

        self._last_sent = now
        self._burst_counter += 1
        return True


# ============== Alert Severity ==============

class AlertSeverity:
    """Alert severity levels."""

    CRITICAL = "critical"  # Immediate action required
    WARNING = "warning"    # Attention needed
    INFO = "info"          # Informational
    DEBUG = "debug"        # Debug only


class AlertFilter:
    """Filter alerts by severity and rules."""

    def __init__(self, min_severity: str = AlertSeverity.INFO):
        self.min_severity = min_severity
        self._severity_order = {
            AlertSeverity.DEBUG: 0,
            AlertSeverity.INFO: 1,
            AlertSeverity.WARNING: 2,
            AlertSeverity.CRITICAL: 3,
        }

    def should_send(self, severity: str, event_type: str) -> bool:
        """Check if alert should be sent."""
        # Check severity level
        event_level = self._severity_order.get(severity, 1)
        min_level = self._severity_order.get(self.min_severity, 1)

        if event_level < min_level:
            return False

        # Additional filtering rules
        # Skip health reports unless degraded
        if event_type == "health_report" and severity == AlertSeverity.INFO:
            return False

        return True


# ============== Main Handler ==============

class TelegramAlertsHandler:
    """Handle events and send Telegram notifications."""

    def __init__(
        self,
        telegram_client: TelegramClientProtocol,
        settings: Any,
        notification_port: Optional[NotificationPort] = None
    ):
        self.telegram = telegram_client
        self.settings = settings
        self.notification_port = notification_port

        # Configuration
        self.lang = str(getattr(settings, "TELEGRAM_LANG", "en")).lower()
        self.silent_hours = self._parse_silent_hours()

        # Throttling
        throttle_sec = float(os.getenv("TELEGRAM_ALERTS_THROTTLE_SEC", "1.0"))
        burst_limit = int(os.getenv("TELEGRAM_ALERTS_BURST_LIMIT", "10"))
        self._throttle = MessageThrottle(throttle_sec, burst_limit)

        # Filtering
        min_severity = os.getenv("TELEGRAM_ALERTS_MIN_SEVERITY", AlertSeverity.INFO)
        self._filter = AlertFilter(min_severity)

        # Stats
        self._stats = {
            "sent": 0,
            "throttled": 0,
            "filtered": 0,
            "failed": 0,
        }

    def _parse_silent_hours(self) -> tuple[int, int] | None:
        """Parse silent hours from settings/env (e.g., '23-07')."""
        silent = getattr(self.settings, "TELEGRAM_SILENT_HOURS", None) or os.getenv("TELEGRAM_SILENT_HOURS", "")
        if not silent:
            return None

        try:
            start, end = str(silent).split("-")
            return (int(start), int(end))
        except (ValueError, TypeError):
            return None

    def _is_silent_time(self) -> bool:
        """Check if current time is in silent hours."""
        if not self.silent_hours:
            return False

        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        start, end = self.silent_hours

        # Handle overnight periods (e.g., 23-07)
        if start > end:
            return hour >= start or hour < end
        else:
            return start <= hour < end

    def _get_severity(self, event_type: str, payload: dict[str, Any]) -> str:
        """Determine alert severity from event type and payload."""
        # Critical events
        if event_type in ["dms_triggered", "broker_connection_lost", "critical_error"]:
            return AlertSeverity.CRITICAL

        # Warning events
        if event_type in ["risk_blocked", "risk_limit_hit", "health_degraded", "trade_failed"]:
            return AlertSeverity.WARNING

        # Info events
        if event_type in ["trade_opened", "trade_closed", "orch_started", "orch_stopped"]:
            return AlertSeverity.INFO

        # Check payload for severity hints
        if "severity" in payload:
            return str(payload["severity"]).lower()

        if "critical" in event_type.lower():
            return AlertSeverity.CRITICAL

        if "error" in event_type.lower() or "fail" in event_type.lower():
            return AlertSeverity.WARNING

        return AlertSeverity.INFO

    async def _send_message(
        self,
        text: str,
        severity: str = AlertSeverity.INFO,
        disable_notification: bool = False
    ) -> None:
        """Send message with error handling and metrics."""
        # Check throttling
        if not self._throttle.allow():
            self._stats["throttled"] += 1
            inc("telegram_alerts_throttled")
            return

        # Check silent hours (except critical)
        if severity != AlertSeverity.CRITICAL and self._is_silent_time():
            disable_notification = True

        try:
            # Send with timeout
            async with asyncio.timeout(15):
                await self.telegram.send_text(
                    text,
                    parse_mode="Markdown",
                    disable_notification=disable_notification
                )

            self._stats["sent"] += 1
            inc("telegram_alerts_sent", severity=severity)

        except asyncio.TimeoutError:
            self._stats["failed"] += 1
            inc("telegram_alerts_timeout")
            _log.warning("telegram_alert_timeout", extra={"preview": text[:120]})

        except Exception as e:
            self._stats["failed"] += 1
            inc("telegram_alerts_error")
            _log.error("telegram_alert_failed", exc_info=True, extra={"error": str(e)})

    # ============== Event Handlers ==============

    async def on_orchestrator_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle orchestrator events."""
        symbol = payload.get("symbol", "?")

        if event_type == EventTopics.ORCH_STARTED:
            text = get_message(self.lang, "orch_started", symbol=symbol)
            await self._send_message(text, AlertSeverity.INFO)

        elif event_type == EventTopics.ORCH_STOPPED:
            text = get_message(self.lang, "orch_stopped", symbol=symbol)
            await self._send_message(text, AlertSeverity.INFO)

        elif event_type == EventTopics.ORCH_PAUSED:
            reason = payload.get("reason", "Manual pause")
            text = get_message(self.lang, "orch_paused", symbol=symbol, reason=reason)
            await self._send_message(text, AlertSeverity.WARNING)

        elif event_type == EventTopics.ORCH_RESUMED:
            text = get_message(self.lang, "orch_resumed", symbol=symbol)
            await self._send_message(text, AlertSeverity.INFO)

    async def on_trade_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle trade events."""
        symbol = payload.get("symbol", "?")

        if event_type == EventTopics.TRADE_OPENED:
            side = payload.get("side", "?")
            amount = float(payload.get("amount", 0))
            price = float(payload.get("price", 0))
            text = get_message(
                self.lang, "trade_opened",
                symbol=symbol, side=side, amount=amount, price=price
            )
            await self._send_message(text, AlertSeverity.INFO)

        elif event_type == EventTopics.TRADE_CLOSED:
            pnl = float(payload.get("pnl", 0))
            pnl_pct = float(payload.get("pnl_pct", 0))
            text = get_message(
                self.lang, "trade_closed",
                symbol=symbol, pnl=pnl, pnl_pct=pnl_pct
            )
            severity = AlertSeverity.INFO if pnl >= 0 else AlertSeverity.WARNING
            await self._send_message(text, severity)

        elif event_type == EventTopics.TRADE_FAILED:
            reason = payload.get("reason", "Unknown error")
            text = get_message(self.lang, "trade_failed", symbol=symbol, reason=reason)
            await self._send_message(text, AlertSeverity.WARNING)

    async def on_risk_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle risk management events."""
        if event_type == EventTopics.RISK_BLOCKED:
            rule = payload.get("rule", "?")
            reason = payload.get("reason", "Risk threshold exceeded")
            text = get_message(self.lang, "risk_blocked", rule=rule, reason=reason)
            await self._send_message(text, AlertSeverity.WARNING)

        elif event_type == EventTopics.RISK_LIMIT_HIT:
            limit_type = payload.get("limit_type", "?")
            current = payload.get("current", 0)
            max_val = payload.get("max", 0)
            text = get_message(
                self.lang, "risk_limit_hit",
                limit_type=limit_type, current=current, max=max_val
            )
            await self._send_message(text, AlertSeverity.WARNING)

    async def on_protective_exit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle protective exit events."""
        symbol = payload.get("symbol", "?")

        if event_type == EventTopics.STOP_LOSS_TRIGGERED:
            loss = float(payload.get("loss", 0))
            text = get_message(self.lang, "stop_loss_triggered", symbol=symbol, loss=abs(loss))
            await self._send_message(text, AlertSeverity.WARNING)

        elif event_type == EventTopics.TAKE_PROFIT_TRIGGERED:
            profit = float(payload.get("profit", 0))
            text = get_message(self.lang, "take_profit_triggered", symbol=symbol, profit=profit)
            await self._send_message(text, AlertSeverity.INFO)

    async def on_health_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle health monitoring events."""
        if event_type == EventTopics.HEALTH_DEGRADED:
            component = payload.get("component", "?")
            status = payload.get("status", "degraded")
            text = get_message(
                self.lang, "health_degraded",
                component=component, status=status
            )
            await self._send_message(text, AlertSeverity.WARNING)

        elif event_type == EventTopics.HEALTH_RESTORED:
            text = get_message(self.lang, "health_restored")
            await self._send_message(text, AlertSeverity.INFO)

    async def on_dms_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle Dead Man's Switch events."""
        if event_type == EventTopics.DMS_TRIGGERED:
            symbol = payload.get("symbol", "ALL")
            action = payload.get("action", "Emergency stop")
            text = get_message(self.lang, "dms_triggered", symbol=symbol, action=action)
            # DMS is always critical - ignore silent hours
            await self._send_message(text, AlertSeverity.CRITICAL, disable_notification=False)

    async def on_regime_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle market regime events."""
        if event_type == EventTopics.REGIME_CHANGED:
            from_regime = payload.get("from", "?")
            to_regime = payload.get("to", "?")
            text = get_message(
                self.lang, "regime_changed",
                from_regime=from_regime, to_regime=to_regime
            )
            await self._send_message(text, AlertSeverity.INFO)

    async def on_generic_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Handle any event generically."""
        # Determine severity
        severity = self._get_severity(event_type, payload)

        # Check if should send
        if not self._filter.should_send(severity, event_type):
            self._stats["filtered"] += 1
            return

        # Format message
        text = f"*Event:* {event_type}\n"

        # Add key fields
        for key in ["symbol", "reason", "error", "message", "status"]:
            if key in payload:
                text += f"*{key.title()}:* {payload[key]}\n"

        # Add trace_id if present
        if trace_id := payload.get("trace_id"):
            text += f"_Trace: {trace_id}_"

        await self._send_message(text, severity)

    def get_stats(self) -> dict[str, int]:
        """Get handler statistics."""
        return self._stats.copy()


# ============== Setup Function ==============

def attach_telegram_alerts(
    bus: EventBusProtocol,
    settings: Any,
    telegram_client: Optional[TelegramClientProtocol] = None
) -> TelegramAlertsHandler:
    """
    Attach Telegram alerts handler to event bus.

    Args:
        bus: Event bus to subscribe to
        settings: Application settings
        telegram_client: Optional Telegram client (will create if not provided)

    Returns:
        Configured alerts handler
    """
    # Create Telegram client if not provided
    if not telegram_client:
        from crypto_ai_bot.app.telegram import TelegramAlerts
        telegram_client = TelegramAlerts(settings=settings)

    # Create handler
    handler = TelegramAlertsHandler(telegram_client, settings)

    # Subscribe to specific events
    event_mapping: dict[str, Callable[[str, dict[str, Any]], Any]] = {
        # Orchestrator events
        EventTopics.ORCH_STARTED: handler.on_orchestrator_event,
        EventTopics.ORCH_STOPPED: handler.on_orchestrator_event,
        EventTopics.ORCH_PAUSED: handler.on_orchestrator_event,
        EventTopics.ORCH_RESUMED: handler.on_orchestrator_event,

        # Trade events
        EventTopics.TRADE_OPENED: handler.on_trade_event,
        EventTopics.TRADE_CLOSED: handler.on_trade_event,
        EventTopics.TRADE_FAILED: handler.on_trade_event,

        # Risk events
        EventTopics.RISK_BLOCKED: handler.on_risk_event,
        EventTopics.RISK_LIMIT_HIT: handler.on_risk_event,

        # Protective exit events
        EventTopics.STOP_LOSS_TRIGGERED: handler.on_protective_exit_event,
        EventTopics.TAKE_PROFIT_TRIGGERED: handler.on_protective_exit_event,

        # Health events
        EventTopics.HEALTH_DEGRADED: handler.on_health_event,
        EventTopics.HEALTH_RESTORED: handler.on_health_event,

        # DMS events
        EventTopics.DMS_TRIGGERED: handler.on_dms_event,

        # Regime events
        EventTopics.REGIME_CHANGED: handler.on_regime_event,
    }

    # Subscribe to events
    for event_type, event_handler in event_mapping.items():
        if hasattr(bus, "on"):
            # bind current values via defaults to avoid late-binding gotcha
            bus.on(event_type, lambda payload, et=event_type, eh=event_handler: eh(et, payload))

    # Subscribe to wildcard patterns if supported (generic handler)
    if hasattr(bus, "on_wildcard"):
        try:
            async def _wildcard_adapter(payload: dict[str, Any]) -> None:
                # Try to infer event type from payload, otherwise use '*'
                ev = payload.get("event") or payload.get("type") or payload.get("event_type") or "*"
                await handler.on_generic_event(str(ev), payload)

            bus.on_wildcard("*", _wildcard_adapter)
        except Exception:
            _log.debug("wildcard_subscriptions_not_supported")

    _log.info(
        "telegram_alerts_attached",
        extra={
            "events_count": len(event_mapping),
            "lang": handler.lang,
            "min_severity": handler._filter.min_severity,
        }
    )

    return handler


__all__ = [
    "TelegramAlertsHandler",
    "AlertSeverity",
    "MessageThrottle",
    "attach_telegram_alerts",
    "get_message",
]
