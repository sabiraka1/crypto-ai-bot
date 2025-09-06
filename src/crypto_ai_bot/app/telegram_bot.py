"""Telegram bot for crypto trading system management.

Located in app layer - handles external interface for bot commands.
Uses orchestrator and storage through existing interfaces.
"""

from __future__ import annotations

import asyncio
import html
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Protocols ==============

class OrchestratorProtocol(Protocol):
    """Protocol for orchestrator interface."""

    def status(self) -> dict[str, Any]: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...


class HealthCheckerProtocol(Protocol):
    """Protocol for health checker."""

    async def check(self) -> dict[str, Any]: ...


# ============== Configuration ==============

@dataclass
class BotConfig:
    """Bot configuration."""

    bot_token: str
    allowed_users: set[int]
    default_symbol: str
    long_poll_sec: int = 30
    ttl_secs: float = 30.0
    throttle_max: int = 5
    throttle_window: int = 10


# ============== Data Classes ==============

@dataclass
class UpdateData:
    """Parsed Telegram update."""

    chat_id: int
    user_id: int
    text: str
    offset: int
    trace_id: str


# ============== Utilities ==============

class RateLimiter:
    """Rate limiting for users."""

    def __init__(self, max_requests: int, window_secs: int):
        self.max_requests = max_requests
        self.window_secs = window_secs
        self.recent: dict[int, list[float]] = {}

    def check_throttle(self, user_id: int) -> bool:
        """Check if user is throttled."""
        now = time.time()
        queue = self.recent.setdefault(user_id, [])

        # Remove old entries
        cutoff = now - self.window_secs
        queue[:] = [t for t in queue if t > cutoff]

        if len(queue) >= self.max_requests:
            return True

        queue.append(now)
        return False


class MessageCache:
    """Deduplication cache for messages."""

    def __init__(self, ttl_secs: float, max_size: int = 2048):
        self.ttl_secs = ttl_secs
        self.max_size = max_size
        self.cache: dict[tuple[int, str], float] = {}

    def is_duplicate(self, user_id: int, text: str) -> bool:
        """Check if message is duplicate."""
        key = (user_id, text.strip().lower())
        now = time.time()

        # Check existing
        if key in self.cache and now - self.cache[key] <= self.ttl_secs:
            return True

        # Add to cache
        self.cache[key] = now

        # Cleanup if too large
        if len(self.cache) > self.max_size:
            cutoff = now - self.ttl_secs
            self.cache = {k: v for k, v in self.cache.items() if v > cutoff}

        return False


# ============== Telegram API ==============

class TelegramAPI:
    """Telegram API client."""

    def __init__(self, bot_token: str):
        self.token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        trace_id: str | None = None,
    ) -> None:
        """Send message to chat."""
        try:
            url = f"{self.base_url}/sendMessage"
            params = {
                "chat_id": str(chat_id),
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true",
            }

            # Build URL with params
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"

            await aget(url, hard_timeout=20.0)

            if trace_id:
                _log.info("telegram_message_sent", extra={"trace_id": trace_id, "chat_id": chat_id})

        except Exception:
            _log.error("telegram_send_failed", exc_info=True, extra={"trace_id": trace_id} if trace_id else {})

    async def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        """Get updates with long polling."""
        url = f"{self.base_url}/getUpdates"
        params = {
            "timeout": str(timeout),
            "offset": str(offset),
            "allowed_updates": '["message"]',
        }

        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"

        try:
            # Add buffer for network delays
            async with asyncio.timeout(timeout + 10):
                resp = await aget(url, hard_timeout=timeout + 8)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("result", []) if isinstance(data, dict) else []
        except asyncio.TimeoutError:
            _log.warning("telegram_get_updates_timeout")
        except Exception:
            _log.error("telegram_get_updates_failed", exc_info=True)

        return []


# ============== Command Handlers ==============

class CommandHandler:
    """Handle bot commands."""

    def __init__(
        self,
        container: Any,
        default_symbol: str,
        api: TelegramAPI,
    ):
        self.container = container
        self.default_symbol = default_symbol
        self.api = api
        self.chat_symbols: dict[int, str] = {}

    def pick_symbol(self, chat_id: int, tail: str | None) -> str:
        """Pick symbol for chat."""
        if tail:
            symbol = canonical(tail.strip())
            if symbol:  # не затираем, если canonical() вернул пустое
                self.chat_symbols[chat_id] = symbol
                return symbol
        return self.chat_symbols.get(chat_id) or self.default_symbol

    def get_orchestrator(self, symbol: str) -> OrchestratorProtocol | None:
        """Get orchestrator for symbol."""
        orchestrators = getattr(self.container, "orchestrators", {})
        if not isinstance(orchestrators, dict):
            return None

        # Try exact match first
        orch = orchestrators.get(symbol)
        if orch:
            return orch

        # Try with slash replacement + upper
        symbol_alt = symbol.replace("-", "/").upper()
        return orchestrators.get(symbol_alt)

    def get_health_checker(self) -> HealthCheckerProtocol | None:
        """Get health checker (support both names)."""
        return getattr(self.container, "health_checker", None) or getattr(self.container, "health", None)

    def get_broker(self) -> Any:
        """Get broker."""
        return getattr(self.container, "broker", None)

    def get_storage(self) -> Any:
        """Get storage facade."""
        return getattr(self.container, "storage", None)

    async def handle_help(self, chat_id: int, trace_id: str) -> None:
        """Show help message."""
        text = (
            "<b>📊 Crypto Trading Bot Commands</b>\n\n"
            "<b>Info:</b>\n"
            "/status - Trading status\n"
            "/pnl - PnL report\n"
            "/today - Today's summary\n"
            "/balance - Account balance\n"
            "/position - Open positions\n"
            "/limits - Risk limits usage\n"
            "/health - System health\n\n"
            "<b>Control:</b>\n"
            "/pause - Pause trading\n"
            "/resume - Resume trading\n"
            "/stop - Stop bot\n\n"
            "<b>Settings:</b>\n"
            "/symbol PAIR - Set active pair\n"
            "/help - This message"
        )
        await self.api.send_message(chat_id, text, trace_id=trace_id)

    async def handle_status(self, chat_id: int, tail: str | None, trace_id: str) -> None:
        """Show orchestrator status."""
        symbol = self.pick_symbol(chat_id, tail)

        orch = self.get_orchestrator(symbol)
        if not orch:
            await self.api.send_message(
                chat_id,
                f"❌ Orchestrator not found for <b>{html.escape(symbol)}</b>",
                trace_id=trace_id,
            )
            return

        try:
            status = orch.status()

            # Format status
            lines = [f"<b>📊 Status {html.escape(symbol)}</b>"]

            # State with emoji
            state = status.get("state", "unknown")
            state_emoji = {
                "running": "🟢",
                "paused": "⏸️",
                "stopped": "🔴",
                "starting": "🔄",
            }.get(str(state).lower(), "❓")
            lines.append(f"{state_emoji} State: <b>{html.escape(str(state))}</b>")

            # Position
            if pos := status.get("position"):
                try:
                    size = float(pos.get("size", 0))
                    entry = float(pos.get("entry_price", 0))
                    if size > 0:
                        lines.append(f"📈 Position: {size:.4f} @ {entry:.2f}")
                except Exception:
                    pass

            # Last trade
            if last_trade := status.get("last_trade_at"):
                lines.append(f"⏰ Last trade: {html.escape(str(last_trade))}")

            # Open orders
            if orders := status.get("open_orders"):
                try:
                    lines.append(f"📝 Open orders: {len(orders)}")
                except Exception:
                    pass

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("status_command_failed", exc_info=True, extra={"symbol": symbol, "trace_id": trace_id})
            await self.api.send_message(
                chat_id,
                f"❌ Failed to get status for {html.escape(symbol)}",
                trace_id=trace_id,
            )

    async def handle_pnl(self, chat_id: int, tail: str | None, trace_id: str) -> None:
        """Show PnL report."""
        symbol = self.pick_symbol(chat_id, tail)

        try:
            storage = self.get_storage()
            if not storage:
                await self.api.send_message(chat_id, "❌ Storage not available", trace_id=trace_id)
                return

            trades_repo = getattr(storage, "trades", None)
            if not trades_repo:
                await self.api.send_message(chat_id, "❌ Trades repository not available", trace_id=trace_id)
                return

            # Today's trades
            today = datetime.now(timezone.utc).date()
            trades = (
                trades_repo.get_by_date_range(start_date=today, end_date=today, symbol=symbol)
                if hasattr(trades_repo, "get_by_date_range")
                else []
            )

            # Calculate PnL
            today_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
            total_trades = len(trades)
            wins = sum(1 for t in trades if float(t.get("pnl", 0) or 0) > 0)
            losses = sum(1 for t in trades if float(t.get("pnl", 0) or 0) < 0)

            lines = [f"<b>💰 PnL Report {html.escape(symbol)}</b>"]
            today_emoji = "📈" if today_pnl >= 0 else "📉"
            lines.append(f"{today_emoji} Today: {today_pnl:+.2f} USDT")

            if total_trades > 0:
                win_rate = wins / total_trades * 100
                lines.append("\n<b>📊 Statistics:</b>")
                lines.append(f"Win rate: {win_rate:.1f}%")
                lines.append(f"Wins: {wins}")
                lines.append(f"Losses: {losses}")
                lines.append(f"Total trades: {total_trades}")
            else:
                lines.append("\nNo trades today")

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("pnl_command_failed", exc_info=True, extra={"symbol": symbol, "trace_id": trace_id})
            await self.api.send_message(chat_id, "❌ Failed to get PnL report", trace_id=trace_id)

    async def handle_balance(self, chat_id: int, trace_id: str) -> None:
        """Show account balance."""
        try:
            broker = self.get_broker()
            if not broker:
                await self.api.send_message(chat_id, "❌ Broker not available", trace_id=trace_id)
                return

            balances = await broker.fetch_balance()

            lines = ["<b>💼 Account Balance</b>"]
            any_found = False

            def _extract(b: Any) -> tuple[float, float, float]:
                # BalanceDTO with attributes
                if hasattr(b, "free") or hasattr(b, "used") or hasattr(b, "total"):
                    fr = float(getattr(b, "free", 0) or 0)
                    us = float(getattr(b, "used", 0) or 0)
                    to = float(getattr(b, "total", fr + us) or (fr + us))
                    return fr, us, to
                # dict-like
                if isinstance(b, dict):
                    fr = float(b.get("free", 0) or 0)
                    us = float(b.get("used", 0) or 0)
                    to = float(b.get("total", fr + us) or (fr + us))
                    return fr, us, to
                # primitive
                val = float(b or 0)
                return val, 0.0, val

            for currency, balance in balances.items():
                free, used, total = _extract(balance)
                if total > 0:
                    any_found = True
                    if currency == "USDT":
                        lines.append("\n💵 USDT:")
                        lines.append(f"  Total: {total:.2f}")
                        lines.append(f"  Available: {free:.2f}")
                        lines.append(f"  In orders: {used:.2f}")
                    else:
                        lines.append(f"{html.escape(str(currency))}: {total:.8f}")

            if not any_found:
                lines.append("No balances found")

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("balance_command_failed", exc_info=True, extra={"trace_id": trace_id})
            await self.api.send_message(chat_id, "❌ Failed to get balance", trace_id=trace_id)

    async def handle_position(self, chat_id: int, tail: str | None, trace_id: str) -> None:
        """Show open positions."""
        symbol = self.pick_symbol(chat_id, tail)

        try:
            broker = self.get_broker()
            if not broker:
                await self.api.send_message(chat_id, "❌ Broker not available", trace_id=trace_id)
                return

            position = await broker.fetch_position(symbol)

            if not position:
                await self.api.send_message(
                    chat_id, f"📊 No open position for {html.escape(symbol)}", trace_id=trace_id
                )
                return

            # Extract fields from object or dict
            def _get(obj: Any, name: str, default: float = 0.0) -> float:
                if hasattr(obj, name):
                    try:
                        return float(getattr(obj, name) or default)
                    except Exception:
                        return default
                if isinstance(obj, dict):
                    try:
                        return float(obj.get(name, default) or default)
                    except Exception:
                        return default
                return default

            size = _get(position, "amount")
            entry = _get(position, "entry_price")
            current = _get(position, "current_price", entry)
            pnl = _get(position, "unrealized_pnl")
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0

            emoji = "🟢" if pnl >= 0 else "🔴"
            lines = [
                f"<b>📈 Position {html.escape(symbol)}</b>",
                f"{emoji} Size: {size:.4f}",
                f"Entry: {entry:.2f}",
                f"Current: {current:.2f}",
                f"PnL: {pnl:+.2f} ({pnl_pct:+.1f}%)",
            ]

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("position_command_failed", exc_info=True, extra={"trace_id": trace_id})
            await self.api.send_message(chat_id, "❌ Failed to get position", trace_id=trace_id)

    async def handle_limits(self, chat_id: int, trace_id: str) -> None:
        """Show risk limits usage."""
        try:
            risk = getattr(self.container, "risk", None)
            if not risk:
                await self.api.send_message(chat_id, "❌ Risk manager not available", trace_id=trace_id)
                return

            lines = ["<b>🛡️ Risk Limits</b>"]
            config = getattr(risk, "config", None)
            if config:
                daily_limit = float(getattr(config, "daily_loss_limit_quote", 0) or 0)
                max_dd = float(getattr(config, "max_drawdown_pct", 0) or 0)
                streak = int(getattr(config, "loss_streak_count", 0) or 0)
                cooldown = float(getattr(config, "cooldown_sec", 0) or 0)
                lines.append(f"\n<b>Daily Loss Limit:</b> {daily_limit:.2f} USDT")
                lines.append(f"<b>Max Drawdown:</b> {max_dd:.1f}%")
                lines.append(f"<b>Loss Streak Limit:</b> {streak} trades")
                lines.append(f"<b>Cooldown:</b> {int(cooldown)} seconds")
            else:
                lines.append("Configuration not available")

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("limits_command_failed", exc_info=True, extra={"trace_id": trace_id})
            await self.api.send_message(chat_id, "❌ Failed to get risk limits", trace_id=trace_id)

    async def handle_today(self, chat_id: int, trace_id: str) -> None:
        """Show today's summary."""
        try:
            storage = self.get_storage()
            if not storage:
                await self.api.send_message(chat_id, "❌ Storage not available", trace_id=trace_id)
                return

            today = datetime.now(timezone.utc).date()
            lines = [f"<b>📅 Today's Summary</b>", f"<i>{today.isoformat()}</i>\n"]

            trades_repo = getattr(storage, "trades", None)
            if trades_repo and hasattr(trades_repo, "get_by_date_range"):
                trades = trades_repo.get_by_date_range(start_date=today, end_date=today)

                total_trades = len(trades)
                pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
                wins = sum(1 for t in trades if float(t.get("pnl", 0) or 0) > 0)
                losses = sum(1 for t in trades if float(t.get("pnl", 0) or 0) < 0)
                volume = sum(abs(float(t.get("amount", 0) or 0) * float(t.get("price", 0) or 0)) for t in trades)

                pnl_emoji = "📈" if pnl >= 0 else "📉"
                lines.append(f"{pnl_emoji} PnL: {pnl:+.2f} USDT")
                lines.append(f"📊 Trades: {total_trades} (W:{wins}/L:{losses})")
                if total_trades > 0:
                    win_rate = wins / total_trades * 100
                    lines.append(f"🎯 Win rate: {win_rate:.1f}%")
                if volume > 0:
                    lines.append(f"💎 Volume: {volume:.2f} USDT")
            else:
                lines.append("No trading data available")

            await self.api.send_message(chat_id, "\n".join(lines), trace_id=trace_id)

        except Exception:
            _log.error("today_command_failed", exc_info=True, extra={"trace_id": trace_id})
            await self.api.send_message(chat_id, "❌ Failed to get today's summary", trace_id=trace_id)

    async def handle_control_command(
        self,
        chat_id: int,
        tail: str | None,
        command: str,
        trace_id: str,
    ) -> None:
        """Handle control commands (pause/resume/stop)."""
        symbol = self.pick_symbol(chat_id, tail)

        orch = self.get_orchestrator(symbol)
        if not orch:
            await self.api.send_message(
                chat_id, f"❌ Orchestrator not found for <b>{html.escape(symbol)}</b>", trace_id=trace_id
            )
            return

        try:
            # Execute command
            method = getattr(orch, command)
            if asyncio.iscoroutinefunction(method):
                await method()
            else:
                method()

            # Get new status
            state = orch.status().get("state", "unknown")

            emoji = {"pause": "⏸️", "resume": "▶️", "stop": "🛑"}.get(command, "✅")
            action = {"pause": "Paused", "resume": "Resumed", "stop": "Stopped"}.get(command, "Done")

            await self.api.send_message(
                chat_id,
                f"{emoji} {action} <b>{html.escape(symbol)}</b>\n"
                f"State: <code>{html.escape(str(state))}</code>",
                trace_id=trace_id,
            )

        except Exception:
            _log.error(f"{command}_command_failed", exc_info=True, extra={"symbol": symbol, "trace_id": trace_id})
            await self.api.send_message(chat_id, f"❌ Failed to {command} {html.escape(symbol)}", trace_id=trace_id)


# ============== Main Bot ==============

class TelegramBotCommands:
    """Telegram bot for system management."""

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_users: list[int],
        container: Any,
        default_symbol: str = "BTC/USDT",
        long_poll_sec: int = 30,
    ):
        # Parse config from env
        ttl = float(os.environ.get("TELEGRAM_BOT_TTL_SECS", "30"))
        throttle = os.environ.get("TELEGRAM_BOT_THROTTLE", "5/10")

        try:
            throttle_max, throttle_win = map(int, throttle.split("/"))
        except ValueError:
            throttle_max, throttle_win = 5, 10

        self.config = BotConfig(
            bot_token=bot_token.strip() if bot_token else "",
            allowed_users={int(u) for u in allowed_users if str(u).strip()},
            default_symbol=canonical(default_symbol),
            long_poll_sec=max(3, int(long_poll_sec)),
            ttl_secs=ttl,
            throttle_max=throttle_max,
            throttle_window=throttle_win,
        )

        self.container = container
        self.api = TelegramAPI(self.config.bot_token)
        self.rate_limiter = RateLimiter(self.config.throttle_max, self.config.throttle_window)
        self.message_cache = MessageCache(self.config.ttl_secs)
        self.command_handler = CommandHandler(container, self.config.default_symbol, self.api)

        self._offset = 0
        self._semaphore = asyncio.Semaphore(int(os.environ.get("TELEGRAM_BOT_CONCURRENCY", "8")))

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized."""
        if not self.config.allowed_users:
            return True
        return user_id in self.config.allowed_users

    def _parse_update(self, update: dict[str, Any]) -> UpdateData | None:
        """Parse Telegram update."""
        try:
            update_id = int(update.get("update_id", 0))
            new_offset = max(self._offset, update_id + 1)

            message = update.get("message") or {}
            chat = message.get("chat") or {}
            from_user = message.get("from") or {}

            chat_id = int(chat.get("id", 0))
            user_id = int(from_user.get("id", 0))
            text = str(message.get("text", "")).strip()

            if not chat_id or not text:
                return None

            return UpdateData(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                offset=new_offset,
                trace_id=generate_trace_id(),
            )

        except (ValueError, TypeError):
            return None

    async def _dispatch_command(self, data: UpdateData) -> None:
        """Route command to handler."""
        text_lower = data.text.lower()
        parts = data.text.split(" ", 1)
        tail = parts[1] if len(parts) > 1 else None

        # Route commands
        if text_lower.startswith(("/help", "/start")):
            await self.command_handler.handle_help(data.chat_id, data.trace_id)

        elif text_lower.startswith("/status"):
            await self.command_handler.handle_status(data.chat_id, tail, data.trace_id)

        elif text_lower.startswith("/pnl"):
            await self.command_handler.handle_pnl(data.chat_id, tail, data.trace_id)

        elif text_lower.startswith("/today"):
            await self.command_handler.handle_today(data.chat_id, data.trace_id)

        elif text_lower.startswith("/balance"):
            await self.command_handler.handle_balance(data.chat_id, data.trace_id)

        elif text_lower.startswith("/position"):
            await self.command_handler.handle_position(data.chat_id, tail, data.trace_id)

        elif text_lower.startswith("/limits"):
            await self.command_handler.handle_limits(data.chat_id, data.trace_id)

        elif text_lower.startswith("/health"):
            await self.command_handler.handle_health(data.chat_id, data.trace_id)

        elif text_lower.startswith("/pause"):
            await self.command_handler.handle_control_command(data.chat_id, tail, "pause", data.trace_id)

        elif text_lower.startswith("/resume"):
            await self.command_handler.handle_control_command(data.chat_id, tail, "resume", data.trace_id)

        elif text_lower.startswith("/stop"):
            await self.command_handler.handle_control_command(data.chat_id, tail, "stop", data.trace_id)

        elif text_lower.startswith("/symbol"):
            # Handle symbol change
            if tail:
                symbol = canonical(tail.strip())
                if symbol:
                    self.command_handler.chat_symbols[data.chat_id] = symbol
                    await self.api.send_message(
                        data.chat_id, f"✅ Active symbol: <b>{html.escape(symbol)}</b>", trace_id=data.trace_id
                    )
                else:
                    await self.api.send_message(
                        data.chat_id,
                        "❌ Invalid symbol. Use format like <b>BTC/USDT</b>.",
                        trace_id=data.trace_id,
                    )
            else:
                current = self.command_handler.pick_symbol(data.chat_id, None)
                await self.api.send_message(
                    data.chat_id,
                    f"Current symbol: <b>{html.escape(current)}</b>\nUse <code>/symbol PAIR</code> to change",
                    trace_id=data.trace_id,
                )

        else:
            # Unknown command
            await self.api.send_message(
                data.chat_id, "❓ Unknown command. Type /help for available commands.", trace_id=data.trace_id
            )

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Process single update."""
        parsed = self._parse_update(update)
        if not parsed:
            return

        self._offset = parsed.offset

        # Authorization
        if not self._is_authorized(parsed.user_id):
            await self.api.send_message(parsed.chat_id, "🚫 Unauthorized", trace_id=parsed.trace_id)
            _log.warning("unauthorized_access", extra={"user_id": parsed.user_id, "trace_id": parsed.trace_id})
            return

        # Rate limiting
        if self.rate_limiter.check_throttle(parsed.user_id):
            await self.api.send_message(parsed.chat_id, "⏳ Rate limit exceeded. Please wait.", trace_id=parsed.trace_id)
            return

        # Deduplication
        if self.message_cache.is_duplicate(parsed.user_id, parsed.text):
            return

        # Log command
        _log.info(
            "telegram_command",
            extra={"user_id": parsed.user_id, "command": parsed.text.split()[0], "trace_id": parsed.trace_id},
        )

        # Dispatch
        await self._dispatch_command(parsed)

    async def run(self) -> None:
        """Main bot loop."""
        if not self.config.bot_token:
            _log.warning("telegram_bot_disabled", extra={"reason": "no_token"})
            return

        _log.info(
            "telegram_bot_started",
            extra={"allowed_users": len(self.config.allowed_users), "default_symbol": self.config.default_symbol},
        )

        while True:
            try:
                # Get updates
                updates = await self.api.get_updates(self._offset, self.config.long_poll_sec)

                # Process in parallel with limit
                if updates:
                    async def process_with_timeout(u: dict[str, Any]) -> None:
                        async with self._semaphore:
                            try:
                                async with asyncio.timeout(self.config.long_poll_sec + 5):
                                    await self._process_update(u)
                            except asyncio.TimeoutError:
                                _log.warning("update_process_timeout")
                            except Exception:
                                _log.error("update_process_failed", exc_info=True)

                    await asyncio.gather(*(process_with_timeout(u) for u in updates), return_exceptions=True)

                # Small delay between polls
                await asyncio.sleep(0.1)

            except Exception:
                _log.error("bot_loop_error", exc_info=True)
                await asyncio.sleep(5)  # Backoff on error
