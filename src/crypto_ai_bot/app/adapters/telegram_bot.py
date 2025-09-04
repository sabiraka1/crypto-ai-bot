from __future__ import annotations

import asyncio
import html
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Protocol

from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger("adapters.telegram_bot")


class OrchestratorNotFoundError(Exception):
    """Raised when orchestrator is not found for symbol."""


class OrchestratorProtocol(Protocol):
    """Protocol for orchestrator interface."""

    def status(self) -> dict[str, Any]: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...


@dataclass
class BotConfig:
    """Bot configuration."""

    bot_token: str
    allowed_users: set[int]
    default_symbol: str
    long_poll_sec: int
    ttl_secs: float
    throttle_max: int
    throttle_window: int


@dataclass
class UpdateData:
    """Parsed update data."""

    chat_id: int
    user_id: int
    text: str
    offset: int


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
        key = (user_id, text.strip())
        now = time.time()

        # Check existing and add if not duplicate
        if key in self.cache and now - self.cache[key] <= self.ttl_secs:
            return True

        # Add to cache
        self.cache[key] = now

        # Cleanup if too large
        if len(self.cache) > self.max_size:
            cutoff = now - self.ttl_secs
            self.cache = {k: v for k, v in self.cache.items() if v > cutoff}

        return False


class TelegramAPI:
    """Telegram API client."""

    def __init__(self, bot_token: str):
        self.token = bot_token

    def _build_url(self, method: str, **params: Any) -> str:
        """Build API URL."""
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return f"https://api.telegram.org/bot{self.token}/{method}?{query}"

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
        """Send message to chat."""
        try:
            url = self._build_url(
                "sendMessage",
                chat_id=str(chat_id),
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview="true",
            )
            # жёсткий cap на всю операцию отправки
            await aget(url, hard_timeout=20.0)
        except Exception:
            _log.error("telegram_reply_failed", exc_info=True)

    async def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        """Get updates from Telegram with timeout."""
        url = self._build_url(
            "getUpdates",
            timeout=str(timeout),
            offset=str(offset),
            # Telegram ожидает JSON-список строк; строка тоже работает, но оставим как есть
            allowed_updates="message",
        )

        try:
            # небольшая подстраховка поверх long-poll (timeout + запас)
            async with asyncio.timeout(timeout + 10):
                resp = await aget(url, hard_timeout=timeout + 8)
                data = resp.json() if resp.status_code == 200 else {}
        except TimeoutError:
            _log.warning("telegram_get_updates_timeout")
            return []
        except Exception:
            _log.error("telegram_get_updates_failed", exc_info=True)
            return []

        if isinstance(data, dict):
            return data.get("result", [])
        return []


class CommandHandler:
    """Handle individual commands."""

    def __init__(self, container: Any, default_symbol: str, api_client: TelegramAPI):
        self.container = container
        self.default_symbol = default_symbol
        self.api = api_client
        self.chat_symbols: dict[int, str] = {}

    def pick_symbol(self, chat_id: int, tail: str | None) -> str:
        """Pick symbol for chat."""
        if tail:
            symbol = canonical(tail.strip())
            if symbol:
                self.chat_symbols[chat_id] = symbol
                return symbol
        return self.chat_symbols.get(chat_id) or self.default_symbol

    def get_orchestrator(self, symbol: str) -> OrchestratorProtocol:
        """Get orchestrator for symbol."""
        orchestrators = getattr(self.container, "orchestrators", None)
        if not isinstance(orchestrators, dict):
            raise OrchestratorNotFoundError("Orchestrators not ready")

        orch = orchestrators.get(symbol)
        if not orch:
            # Try with slash replacement
            orch = orchestrators.get(symbol.replace("-", "/").upper())

        if not orch:
            raise OrchestratorNotFoundError(f"Orchestrator not found for {symbol}")

        return orch

    async def handle_help(self, chat_id: int) -> None:
        """Handle help command."""
        text = (
            "<b>Available commands</b>\n"
            "/help – show this help\n"
            "/symbol SYMBOL – set default symbol\n"
            "/status [SYMBOL] – show orchestrator status\n"
            "/start_trade [SYMBOL] – start orchestrator\n"
            "/stop_trade [SYMBOL] – stop orchestrator\n"
            "/pause [SYMBOL] – pause orchestrator\n"
            "/resume [SYMBOL] – resume orchestrator\n"
        )
        await self.api.send_message(chat_id, text)

    async def handle_symbol(self, chat_id: int, tail: str | None) -> None:
        """Handle symbol command."""
        if not tail or not tail.strip():
            current = self.chat_symbols.get(chat_id) or self.default_symbol
            await self.api.send_message(chat_id, f"Current symbol: <code>{html.escape(current)}</code>")
            return

        symbol = canonical(tail.strip())
        self.chat_symbols[chat_id] = symbol
        await self.api.send_message(chat_id, f"Default symbol set: <b>{html.escape(symbol)}</b>")

    async def handle_status(self, chat_id: int, tail: str | None) -> None:
        """Handle status command."""
        symbol = self.pick_symbol(chat_id, tail)

        try:
            orch = self.get_orchestrator(symbol)
            status = orch.status()
        except OrchestratorNotFoundError:
            await self.api.send_message(chat_id, f"Orchestrator not found for <b>{html.escape(symbol)}</b>")
            return
        except Exception:
            _log.error("orch_status_failed", extra={"symbol": symbol}, exc_info=True)
            await self.api.send_message(chat_id, f"Status failed for <b>{html.escape(symbol)}</b>")
            return

        lines = [f"<b>Status {html.escape(symbol)}</b>"]
        for key in ("state", "open_orders", "position", "last_signal", "last_trade_at"):
            if key in status:
                value = status[key]
                if isinstance(value, (dict, list)):
                    value = str(value)
                lines.append(f"- {key}: <code>{html.escape(str(value))}</code>")

        await self.api.send_message(chat_id, "\n".join(lines))

    async def handle_orchestrator_command(
        self, chat_id: int, tail: str | None, method: str, success_text: str
    ) -> None:
        """Handle orchestrator method call."""
        symbol = self.pick_symbol(chat_id, tail)

        try:
            orch = self.get_orchestrator(symbol)
            func = getattr(orch, method)

            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                func()

            status = orch.status()
            state = status.get("state", "unknown")

            await self.api.send_message(
                chat_id,
                f"{success_text} <b>{html.escape(symbol)}</b>\nstate: <code>{html.escape(str(state))}</code>",
            )

        except OrchestratorNotFoundError:
            await self.api.send_message(chat_id, f"Orchestrator not found for <b>{html.escape(symbol)}</b>")
        except Exception:
            _log.error("orch_call_failed", extra={"symbol": symbol, "method": method}, exc_info=True)
            await self.api.send_message(chat_id, f"{method} failed for <b>{html.escape(symbol)}</b>")


class UpdateParser:
    """Parse Telegram updates."""

    @staticmethod
    def parse(update: dict[str, Any], current_offset: int) -> UpdateData | None:
        """Parse single update."""
        try:
            update_id = int(update.get("update_id", 0))
            new_offset = max(current_offset, update_id + 1)

            message = update.get("message") or {}
            chat = message.get("chat") or {}
            from_user = message.get("from") or {}

            chat_id = int(chat.get("id", 0) or 0)
            user_id = int(from_user.get("id", 0) or 0)
            text = str(message.get("text") or "").strip()

            if not chat_id or not text:
                return None

            return UpdateData(chat_id=chat_id, user_id=user_id, text=text, offset=new_offset)
        except (ValueError, TypeError):
            return None


class TelegramBotCommands:
    """Long-polling bot for admin commands."""

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_users: list[int],
        container: Any,
        default_symbol: str,
        long_poll_sec: int = 30,
    ) -> None:
        # Parse environment configs
        ttl = float(os.environ.get("TELEGRAM_BOT_TTL_SECS", "30") or 30.0)
        throttle_str = os.environ.get("TELEGRAM_BOT_THROTTLE", "3/5")

        try:
            throttle_max, throttle_win = (int(x) for x in throttle_str.split("/", 1))
        except ValueError:
            throttle_max, throttle_win = 3, 5

        self.config = BotConfig(
            bot_token=(bot_token or "").strip(),
            allowed_users={int(x) for x in allowed_users if str(x).strip()},
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
        self.parser = UpdateParser()
        self._offset = 0

        # ограничитель параллельных обработок апдейтов
        self._sem = asyncio.Semaphore(int(os.environ.get("TELEGRAM_BOT_CONCURRENCY", "8") or "8"))

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized."""
        if not self.config.allowed_users:
            return True
        return user_id in self.config.allowed_users

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Process single update."""
        parsed = self.parser.parse(update, self._offset)
        if not parsed:
            return

        self._offset = parsed.offset

        # Authorization check
        if not self._is_authorized(parsed.user_id):
            await self.api.send_message(parsed.chat_id, "Unauthorized.")
            return

        # Rate limiting
        if self.rate_limiter.check_throttle(parsed.user_id):
            await self.api.send_message(parsed.chat_id, "Rate limit, try later.")
            return

        # Deduplication
        if self.message_cache.is_duplicate(parsed.user_id, parsed.text):
            return

        # Dispatch command
        await self._dispatch_command(parsed.chat_id, parsed.text)

    async def _dispatch_command(self, chat_id: int, text: str) -> None:
        """Dispatch command to handler."""
        text = text.strip()
        lower_text = text.lower()

        # Split command and arguments
        parts = text.split(" ", 1)
        tail = parts[1] if len(parts) > 1 else ""

        # Route commands
        if lower_text.startswith(("/start", "/help")):
            await self.command_handler.handle_help(chat_id)
        elif lower_text.startswith("/symbol"):
            await self.command_handler.handle_symbol(chat_id, tail)
        elif lower_text.startswith("/status"):
            await self.command_handler.handle_status(chat_id, tail)
        elif lower_text.startswith("/start_trade"):
            await self.command_handler.handle_orchestrator_command(chat_id, tail, "start", "Started")
        elif lower_text.startswith(("/stop_trade", "/stop")):
            await self.command_handler.handle_orchestrator_command(chat_id, tail, "stop", "Stopped")
        elif lower_text.startswith("/pause"):
            await self.command_handler.handle_orchestrator_command(chat_id, tail, "pause", "Paused")
        elif lower_text.startswith("/resume"):
            await self.command_handler.handle_orchestrator_command(chat_id, tail, "resume", "Resumed")
        else:
            # Unknown command
            symbol = self.command_handler.pick_symbol(chat_id, None)
            await self.api.send_message(
                chat_id,
                f"Unknown command. Type /help\nCurrent symbol: <code>{html.escape(symbol)}</code>",
            )

    async def _fetch_updates(self) -> list[dict[str, Any]]:
        """Fetch updates from Telegram."""
        try:
            return await self.api.get_updates(self._offset, self.config.long_poll_sec)
        except Exception:
            _log.error("telegram_getupdates_failed", exc_info=True)
            return []

    async def _guarded_process(self, update: dict[str, Any]) -> None:
        async with self._sem:
            try:
                # не задерживаем обработку каждого апдейта дольше, чем long-poll
                async with asyncio.timeout(self.config.long_poll_sec + 5):
                    await self._process_update(update)
            except TimeoutError:
                _log.warning("telegram_update_timeout")
            except Exception:
                _log.error("telegram_update_process_failed", exc_info=True)

    async def run(self) -> None:
        """Main long-polling loop."""
        if not self.config.bot_token:
            _log.warning("telegram_bot_token_missing")
            return

        _log.info("telegram_bot_started")

        while True:
            updates = await self._fetch_updates()

            # параллелим обработку входящих апдейтов с ограничением
            if updates:
                await asyncio.gather(*[self._guarded_process(u) for u in updates], return_exceptions=True)

            await asyncio.sleep(0.2)
