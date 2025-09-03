from __future__ import annotations
from typing import Any, cast
import asyncio
import html
import os
import time

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical


def _getv(d: Any) -> Any:
    def _inner(k: str) -> Any:
        if isinstance(d, dict):
            return d.get(k, {})
        try:
            return getattr(d, k.lower(), {})  # noqa: TRY300
        except Exception:  # noqa: BLE001
            return {}  # noqa: TRY300
    return _inner  # noqa: TRY300

_log = get_logger("adapters.telegram_bot")

_TTL = float(os.environ.get("TELEGRAM_BOT_TTL_SECS", "30") or 30.0)
_THR = os.environ.get("TELEGRAM_BOT_THROTTLE", "3/5")
try:
    _THR_N, _THR_WIN = (int(x) for x in _THR.split("/", 1))
except Exception:  # noqa: BLE001  # fallback
    _THR_N, _THR_WIN = 3, 5


def _split_symbol(sym: str) -> tuple[str, str]:
    try:
        b, q = sym.split("/", 1)
        return b.upper(), q.upper()  # noqa: TRY300
    except Exception:  # noqa: BLE001
        return sym.upper(), ""  # noqa: TRY300


class TelegramBotCommands:
    """
    Long-poll ѹ .
    """

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
        self._cache: dict[tuple[int, str], tuple[float, str]] = {}
        self._recent: dict[int, list[float]] = {}

    # --------------------- Ѹ ---------------------

    def _allow(self, user_id: int | None) -> bool:
        if not self._allowed:
            return True
        try:
            return int(user_id or 0) in self._allowed  # noqa: TRY300
        except Exception:  # noqa: BLE001
            return False  # noqa: TRY300

    def _throttle(self, user_id: int) -> bool:
        now = time.time()
        q = self._recent.setdefault(user_id, [])
        while q and q[0] < now - _THR_WIN:
            q.pop(0)
        if len(q) >= _THR_N:
            return False
        q.append(now)
        return True

    def _cache_get(self, chat_id: int, key: str) -> str | None:
        k = (chat_id, key)
        v = self._cache.get(k)
        if not v:
            return None
        ts, text = v
        if time.time() - ts <= _TTL:
            return text
        self._cache.pop(k, None)
        return None

    def _cache_put(self, chat_id: int, key: str, text: str) -> None:
        self._cache[(chat_id, key)] = (time.time(), text)

    def _endpoint(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    async def _get_updates(self) -> dict[str, Any]:
        try:
            params = {"timeout": self._lp_sec, "offset": self._offset}
            resp = await aget(self._endpoint("getUpdates"), params=params, timeout=self._lp_sec + 5)
            if resp.status_code != 200:
                _log.warning("tg_get_updates_non_200", extra={"status": resp.status_code})
                return {"ok": False, "result": []}  # noqa: TRY300
            return cast(dict[str, Any], resp.json())
        except Exception:  # noqa: BLE001
            _log.error("tg_get_updates_failed", exc_info=True)
            return {"ok": False, "result": []}

    async def _reply(self, chat_id: int, text: str) -> None:
        try:
            t = TelegramAlerts(bot_token=self._token, chat_id=str(chat_id))
            await t.send(text)
        except Exception:  # noqa: BLE001
            _log.error("tg_reply_failed", extra={"chat_id": chat_id}, exc_info=True)

    def _pick_symbol(self, chat_id: int, text: str) -> str:
        parts = text.strip().split()
        if len(parts) >= 2 and "/" in parts[1]:
            sym = canonical(parts[1])
            self._chat_symbol[chat_id] = sym
            return sym
        return self._chat_symbol.get(chat_id, self._default_symbol)

    def _get_orchestrator(self, symbol: str) -> Any | None:
        orchs = getattr(self._container, "orchestrators", {}) or {}
        return orchs.get(symbol) or orchs.get(symbol.replace("-", "/").upper())

    # ---------------------  ---------------------

    async def _cmd_help(self, chat_id: int) -> None:
        key = "help"
        cached = self._cache_get(chat_id, key)
        if cached:
            await self._reply(chat_id, cached)
            return
        txt = (
            " <b></b>\n"
            "/help  сс \n"
            "/symbols  сѿѵ с\n"
            "/set &lt;SYM&gt;   я ѰѰ\n"
            "/status [SYM]  сѰс ѺсѰѾѰ\n"
            "/balance [SYM]  с  Ѷ\n"
            "/limits  ѵѸ  Ѹс\n"
            "/risk [SYM]  сѷ Ѿ\n"
        )
        self._cache_put(chat_id, key, txt)
        await self._reply(chat_id, txt)

    async def _cmd_symbols(self, chat_id: int) -> None:
        key = "symbols"
        cached = self._cache_get(chat_id, key)
        if cached:
            await self._reply(chat_id, cached)
            return
        orchs = getattr(self._container, "orchestrators", {}) or {}
        syms = ", ".join(sorted(orchs.keys())) or ""
        cur = self._chat_symbol.get(chat_id, self._default_symbol)
        txt = f" <b></b>\nсѿ: <code>{html.escape(syms)}</code>\nѸ: <code>{html.escape(cur)}</code>"
        self._cache_put(chat_id, key, txt)
        await self._reply(chat_id, txt)

    async def _cmd_set(self, chat_id: int, text: str) -> None:
        parts = text.strip().split()
        if len(parts) < 2 or "/" not in parts[1]:
            await self._reply(chat_id, "сѷ: <code>/set BTC/USDT</code>")
            return
        sym = canonical(parts[1])
        orchs = getattr(self._container, "orchestrators", {}) or {}
        if sym not in orchs:
            await self._reply(chat_id, f" ѺсѰѾ я <code>{html.escape(sym)}</code>  ")
            return
        self._chat_symbol[chat_id] = sym
        await self._reply(chat_id, f" сѰ ѵѸ с: <code>{html.escape(sym)}</code>")

    async def _cmd_status(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"  ѺсѰѾѰ я <code>{html.escape(symbol)}</code>")
            return
        st = orch.status()
        started = "" if st.get("started") else ""
        paused = "⏸" if st.get("paused") else "️"
        lines = [f"{started} <b>Status</b> {paused} <code>{html.escape(symbol)}</code>"]
        loops = st.get("loops", {})
        for name, info in loops.items():
            mark = "" if info.get("task_alive") else ""
            lines.append(f"{mark} {name} (int={info.get('interval_sec')}, enabled={info.get('enabled')})")
        await self._reply(chat_id, "\n".join(lines))

    async def _cmd_pause(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"  ѺсѰѾѰ я <code>{html.escape(symbol)}</code>")
            return
        await orch.pause()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_resume(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"  ѺсѰѾѰ я <code>{html.escape(symbol)}</code>")
            return
        await orch.resume()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_stop(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"  ѺсѰѾѰ я <code>{html.escape(symbol)}</code>")
            return
        await orch.stop()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_limits(self, chat_id: int) -> None:
        key = "limits"
        cached = self._cache_get(chat_id, key)
        if cached:
            await self._reply(chat_id, cached)
            return
        risk = getattr(self._container, "risk", None)
        cfg = getattr(risk, "config", None)
        if not cfg:
            await self._reply(chat_id, " RiskConfig сѿ")
            return
        txt = (
            " <b></b>\n"
            f"cooldown: <code>{getattr(cfg, 'cooldown_sec', 0)}s</code>\n"
            f"max_spread: <code>{getattr(cfg, 'max_spread_pct', 0)}</code>%\n"
            f"max_position_base: <code>{getattr(cfg, 'max_position_base', 0)}</code>\n"
            f"max_orders/hour: <code>{getattr(cfg, 'max_orders_per_hour', 0)}</code>\n"
        )
        self._cache_put(chat_id, key, txt)
        await self._reply(chat_id, txt)

    async def _cmd_risk(self, chat_id: int, symbol: str) -> None:
        parts = [" <b>с (ѵ)</b>"]
        st = getattr(self._container, "storage", None)
        cfg = getattr(getattr(self._container, "risk", None), "config", None)
        try:
            if st and hasattr(st, "trades") and hasattr(st.trades, "daily_turnover_quote"):
                tq = st.trades.daily_turnover_quote(symbol)
                parts.append(f"turnover_today: <code>{tq}</code>")
        except Exception:  # noqa: BLE001
            _log.error("risk_calc_turnover_failed", exc_info=True)

        try:
            if cfg and getattr(cfg, "max_orders_per_hour", 0) and st and hasattr(st, "trades") and hasattr(st.trades, "count_orders_last_minutes"):
                cnt = st.trades.count_orders_last_minutes(symbol, 60)
                mx = getattr(cfg, "max_orders_per_hour", 0)
                parts.append(f"orders_60m: <code>{cnt}/{mx}</code>")
        except Exception:  # noqa: BLE001
            _log.error("risk_calc_orders_failed", exc_info=True)

        await self._reply(chat_id, "\n".join(parts))

    async def _cmd_balance(self, chat_id: int, symbol: str) -> None:
        broker = getattr(self._container, "broker", None)
        if not broker:
            await self._reply(chat_id, " broker сѿ")
            return
        base, quote = _split_symbol(symbol)
        try:
            b = await broker.fetch_balance()
            gv = _getv(b)
            base, quote = (symbol.split('/') + ['',''])[:2]
            base_free = gv(base).get('free') or gv(base).get('total') or '0'
            quote_free = gv(quote).get('free') or gv(quote).get('total') or '0'
            await self._reply(chat_id, f" <b>с</b> <code>{html.escape(symbol)}</code>\n"
                                       f"{base}: <code>{base_free}</code>\n{quote}: <code>{quote_free}</code>")
        except Exception:  # noqa: BLE001
            await self._reply(chat_id, "️  Ѵс Ѹ с")

    # --------------------- ѹ Ѿ run() ---------------------

    async def run(self) -> None:
        """ѹ Ѹ long-polling я ѵя   Telegram"""
        _log.info("telegram_bot_commands_started")

        while True:
            try:
                data = await self._get_updates()

                if data.get("ok"):
                    for update in data.get("result", []):
                        self._offset = update.get("update_id", 0) + 1

                        msg = update.get("message", {})
                        if not msg:
                            continue

                        user_id = msg.get("from", {}).get("id")
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "").strip()

                        if not text or not chat_id:
                            continue

                        if not self._allow(user_id):
                            await self._reply(chat_id, " сѿ ѵѵ")
                            continue

                        if not self._throttle(user_id):
                            await self._reply(chat_id, "️ Ѻ  Ѿс, ѵ")
                            continue

                        if text.startswith("/"):
                            cmd = text.split()[0].lower()

                            if cmd == "/help":
                                await self._cmd_help(chat_id)
                            elif cmd == "/symbols":
                                await self._cmd_symbols(chat_id)
                            elif cmd == "/set":
                                await self._cmd_set(chat_id, text)
                            elif cmd == "/limits":
                                await self._cmd_limits(chat_id)
                            else:
                                symbol = self._pick_symbol(chat_id, text)

                                if cmd == "/status":
                                    await self._cmd_status(chat_id, symbol)
                                elif cmd == "/pause":
                                    await self._cmd_pause(chat_id, symbol)
                                elif cmd == "/resume":
                                    await self._cmd_resume(chat_id, symbol)
                                elif cmd == "/stop":
                                    await self._cmd_stop(chat_id, symbol)
                                elif cmd == "/balance":
                                    await self._cmd_balance(chat_id, symbol)
                                elif cmd == "/risk":
                                    await self._cmd_risk(chat_id, symbol)

                await asyncio.sleep(1)

            except Exception:  # noqa: BLE001
                _log.error("telegram_bot_run_error", exc_info=True)
                await asyncio.sleep(5)
