from __future__ import annotations

import asyncio
import html
import os
import time
from typing import Any, cast
import urllib.parse

from crypto_ai_bot.app.telegram import TelegramAlerts
from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger("adapters.telegram_bot")


def _getv(d: Any) -> Any:
    """Safe accessor that works with dicts and objects (case-insensitive for attrs)."""

    def _inner(k: str) -> Any:
        try:
            if isinstance(d, dict):
                return d.get(k, {})
            return getattr(d, k.lower(), {})
        except AttributeError:
            return {}

    return _inner


_TTL = float(os.environ.get("TELEGRAM_BOT_TTL_SECS", "30") or 30.0)
_THR = os.environ.get("TELEGRAM_BOT_THROTTLE", "3/5")
try:
    _THR_N, _THR_WIN = (int(x) for x in _THR.split("/", 1))
except ValueError:
    _THR_N, _THR_WIN = 3, 5


def _split_symbol(sym: str) -> tuple[str, str]:
    try:
        b, q = sym.split("/", 1)
        return b.upper(), q.upper()
    except ValueError:
        return sym.upper(), ""


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
        self._token = (bot_token or "").strip()
        self._allowed = {int(x) for x in allowed_users if str(x).strip()}
        self._container = container
        self._alerts = TelegramAlerts(bot_token=bot_token, chat_id="")
        self._default_symbol = canonical(default_symbol)
        self._offset = 0
        self._lp_sec = max(3, int(long_poll_sec))
        self._chat_symbol: dict[int, str] = {}
        self._cache: dict[tuple[int, str], tuple[float, str | None]] = {}
        self._recent: dict[int, list[float]] = {}

    def _allow(self, user_id: int | None) -> bool:
        if not self._allowed:
            return True
        try:
            return int(user_id or 0) in self._allowed
        except ValueError:
            return False

    def _throttle(self, user_id: int) -> bool:
        now = time.time()
        q = self._recent.setdefault(user_id, [])
        while q and q[0] < now - float(_THR_WIN):
            q.pop(0)
        if len(q) >= int(_THR_N):
            return True
        q.append(now)
        return False

    def _dedup(self, user_id: int, text: str) -> bool:
        key = (user_id, text.strip())
        ts = time.time()
        ts_prev, _ = self._cache.get(key, (0.0, None))
        if ts - ts_prev <= _TTL:
            return True
        self._cache[key] = (ts, None)
        if len(self._cache) > 2048:
            cutoff = ts - _TTL
            for k, (t, _) in list(self._cache.items())[:1024]:
                if t < cutoff:
                    self._cache.pop(k, None)
        return False

    def _api(self, method: str, **params: Any) -> str:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return f"https://api.telegram.org/bot{self._token}/{method}?{q}"

    async def _reply(self, chat_id: int, text: str, *, parse_mode: str = "HTML") -> None:
        try:
            url = self._api(
                "sendMessage",
                chat_id=str(chat_id),
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview="true",
            )
            await aget(url)
        except Exception:
            _log.error("telegram_reply_failed", exc_info=True)

    def _pick_symbol(self, chat_id: int, tail: str | None) -> str:
        if tail:
            s = canonical(tail.strip())
            if s:
                self._chat_symbol[chat_id] = s
                return s
        return self._chat_symbol.get(chat_id) or self._default_symbol

    def _orch(self, symbol: str) -> Any:
        c = self._container
        orchs = getattr(c, "orchestrators", None)
        if not isinstance(orchs, dict):
            raise RuntimeError("Orchestrators not ready")
        return orchs.get(symbol) or orchs.get(symbol.replace("-", "/").upper())

    async def _cmd_help(self, chat_id: int) -> None:
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
        await self._reply(chat_id, text)

    async def _cmd_symbol(self, chat_id: int, tail: str | None) -> None:
        if not tail or not tail.strip():
            cur = self._chat_symbol.get(chat_id) or self._default_symbol
            await self._reply(chat_id, f"Current symbol: <code>{html.escape(cur)}</code>")
            return
        s = canonical(tail.strip())
        self._chat_symbol[chat_id] = s
        await self._reply(chat_id, f"Default symbol set: <b>{html.escape(s)}</b>")

    async def _cmd_status(self, chat_id: int, tail: str | None) -> None:
        sym = self._pick_symbol(chat_id, tail)
        orch = self._orch(sym)
        if not orch:
            await self._reply(chat_id, f"Orchestrator not found for <b>{html.escape(sym)}</b>")
            return
        try:
            st = orch.status()
        except Exception as e:
            _log.error("orch_status_failed", extra={"symbol": sym}, exc_info=True)
            await self._reply(chat_id, f"Status failed: <code>{html.escape(str(e))}</code>")
            return
        lines = [f"<b>Status {html.escape(sym)}</b>"]
        for k in ("state", "open_orders", "position", "last_signal", "last_trade_at"):
            if k in st:
                v = st[k]
                if isinstance(v, dict | list):
                    v = str(v)
                lines.append(f"- {k}: <code>{html.escape(str(v))}</code>")
        await self._reply(chat_id, "\n".join(lines))

    async def _cmd_simple_call(
        self, chat_id: int, tail: str | None, *, sym_first: bool, method: str, ok_text: str
    ) -> None:
        sym = self._pick_symbol(chat_id, tail if sym_first else None)
        orch = self._orch(sym)
        if not orch:
            await self._reply(chat_id, f"Orchestrator not found for <b>{html.escape(sym)}</b>")
            return
        try:
            fn = getattr(orch, method)
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                fn()
            st = orch.status()
            await self._reply(
                chat_id,
                f"{ok_text} <b>{html.escape(sym)}</b>\nstate: <code>{html.escape(str(st.get('state')))}</code>",
            )
        except Exception as e:
            _log.error("orch_call_failed", extra={"symbol": sym, "method": method}, exc_info=True)
            await self._reply(chat_id, f"{method} failed: <code>{html.escape(str(e))}</code>")

    async def run(self) -> None:
        """Main long-polling loop."""
        if not self._token:
            _log.warning("telegram_bot_token_missing")
            return

        _log.info("telegram_bot_started")

        while True:
            try:
                url = self._api(
                    "getUpdates",
                    timeout=str(self._lp_sec + 5),
                    offset=str(self._offset),
                    allowed_updates="message",
                )
                data = await aget(url)
                updates = cast(dict, data).get("result", []) if isinstance(data, dict) else []
            except Exception:
                _log.error("telegram_getupdates_failed", exc_info=True)
                await asyncio.sleep(1.0)
                continue

            for upd in updates:
                try:
                    self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    user = msg.get("from") or {}
                    chat_id = int(chat.get("id", 0) or 0)
                    user_id = int(user.get("id", 0) or 0)
                    text = str(msg.get("text") or "").strip()

                    if not chat_id or not text:
                        continue

                    if not self._allow(user_id):
                        await self._reply(chat_id, "Unauthorized.")
                        continue

                    if self._throttle(user_id):
                        await self._reply(chat_id, "Rate limit, try later.")
                        continue

                    if self._dedup(user_id, text):
                        continue

                    await self._dispatch(chat_id, text)
                except Exception:
                    _log.error("telegram_update_process_failed", exc_info=True)

            await asyncio.sleep(0.2)

    async def _dispatch(self, chat_id: int, text: str) -> None:
        t = text.strip()
        low = t.lower()

        # Split command and tail
        parts = t.split(" ", 1)
        tail = parts[1] if len(parts) > 1 else ""

        if low.startswith("/start") or low.startswith("/help"):
            await self._cmd_help(chat_id)
        elif low.startswith("/symbol"):
            await self._cmd_symbol(chat_id, tail)
        elif low.startswith("/status"):
            await self._cmd_status(chat_id, tail)
        elif low.startswith("/start_trade"):
            await self._cmd_simple_call(chat_id, tail, sym_first=True, method="start", ok_text="Started")
        elif low.startswith("/stop_trade") or low.startswith("/stop"):
            await self._cmd_simple_call(chat_id, tail, sym_first=True, method="stop", ok_text="Stopped")
        elif low.startswith("/pause"):
            await self._cmd_simple_call(chat_id, tail, sym_first=True, method="pause", ok_text="Paused")
        elif low.startswith("/resume"):
            await self._cmd_simple_call(chat_id, tail, sym_first=True, method="resume", ok_text="Resumed")
        else:
            # Unknown command
            base, quote = _split_symbol(self._pick_symbol(chat_id, None))
            await self._reply(
                chat_id,
                "Unknown command. Type /help\n"
                f"Current symbol: <code>{html.escape(base + '/' + quote if quote else base)}</code>",
            )
