from __future__ import annotations

import asyncio
import html
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.http_client import aget  # для getUpdates
from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger("adapters.telegram_bot")


def _split_symbol(sym: str) -> Tuple[str, str]:
    try:
        b, q = sym.split("/", 1)
        return b.upper(), q.upper()
    except Exception:
        return sym.upper(), ""


class TelegramBotCommands:
    """
    Лёгкий long-poll бот команд (входящие сообщения → действия).
    Требует: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (для исходящих алёртов не обязателен),
             TELEGRAM_ALLOWED_USERS (csv id; пусто => разрешены все),
             TELEGRAM_BOT_COMMANDS_ENABLED=1.

    Архитектура:
      - получение апдейтов: getUpdates (long polling)
      - ответы: через TelegramAlerts (единый HTTP слой)
      - доступ к оркестраторам/хранилищу/брокеру — через контейнер
    """

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_users: List[int],
        container: Any,
        default_symbol: str,
        long_poll_sec: int = 30,
    ) -> None:
        self._token = (bot_token or "").strip()
        self._allowed = set(int(x) for x in allowed_users if str(x).strip())
        self._container = container
        self._alerts = TelegramAlerts(bot_token=bot_token, chat_id="")  # будем указывать chat_id в send()
        self._default_symbol = canonical(default_symbol)
        self._offset = 0
        self._lp_sec = max(3, int(long_poll_sec))
        self._chat_symbol: Dict[int, str] = {}  # chat_id -> symbol

    def _allow(self, user_id: Optional[int]) -> bool:
        if not self._allowed:
            return True
        try:
            return int(user_id or 0) in self._allowed
        except Exception:
            return False

    def _endpoint(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    async def _get_updates(self) -> Dict[str, Any]:
        try:
            params = {"timeout": self._lp_sec, "offset": self._offset}
            resp = await aget(self._endpoint("getUpdates"), params=params, timeout=self._lp_sec + 5)
            if resp.status_code != 200:
                _log.warning("tg_get_updates_non_200", extra={"status": resp.status_code})
                return {"ok": False, "result": []}
            return resp.json()
        except Exception:
            _log.error("tg_get_updates_failed", exc_info=True)
            return {"ok": False, "result": []}

    async def _reply(self, chat_id: int, text: str) -> None:
        try:
            t = TelegramAlerts(bot_token=self._token, chat_id=str(chat_id))
            await t.send(text)
        except Exception:
            _log.error("tg_reply_failed", extra={"chat_id": chat_id}, exc_info=True)

    def _pick_symbol(self, chat_id: int, text: str) -> str:
        # попытка извлечь символ из аргумента команды: "/status ETH/USDT"
        parts = text.strip().split()
        if len(parts) >= 2 and "/" in parts[1]:
            sym = canonical(parts[1])
            self._chat_symbol[chat_id] = sym
            return sym
        # иначе берём из привязки чата или дефолт
        return self._chat_symbol.get(chat_id, self._default_symbol)

    def _get_orchestrator(self, symbol: str) -> Optional[Any]:
        orchs = getattr(self._container, "orchestrators", {}) or {}
        return orchs.get(symbol) or orchs.get(symbol.replace("-", "/").upper())

    async def _cmd_help(self, chat_id: int) -> None:
        txt = (
            "📋 <b>Команды</b>\n"
            "/help — список команд\n"
            "/symbols — доступные символы; /set &lt;SYM&gt; — запомнить для чата\n"
            "\n"
            "📊 <b>Мониторинг</b>\n"
            "/status [SYM] — статус оркестратора\n"
            "/health [SYM] — storage/broker/bus ок?\n"
            "/balance [SYM] — баланс base/quote на бирже\n"
            "/position [SYM] — локальная позиция (base) и оценка\n"
            "/limits — текущие лимиты риска\n"
            "/risk [SYM] — использование лимитов (≈)\n"
            "/today [SYM] — сделки/turnover за сегодня\n"
            "/pnl [SYM] — PnL за сегодня\n"
            "/stats [SYM] — win rate и средний профит (7d)\n"
            "\n"
            "🕹 <b>Управление</b>\n"
            "/pause [SYM] — пауза\n"
            "/resume [SYM] — продолжить\n"
            "/stop [SYM] — остановить\n"
        )
        await self._reply(chat_id, txt)

    async def _cmd_symbols(self, chat_id: int) -> None:
        orchs = getattr(self._container, "orchestrators", {}) or {}
        syms = ", ".join(sorted(orchs.keys())) or "—"
        cur = self._chat_symbol.get(chat_id, self._default_symbol)
        await self._reply(chat_id, f"🔣 <b>Символы</b>\nДоступно: <code>{html.escape(syms)}</code>\nТекущий: <code>{html.escape(cur)}</code>")

    async def _cmd_set(self, chat_id: int, text: str) -> None:
        parts = text.strip().split()
        if len(parts) < 2 or "/" not in parts[1]:
            await self._reply(chat_id, "Использование: <code>/set BTC/USDT</code>")
            return
        sym = canonical(parts[1])
        orchs = getattr(self._container, "orchestrators", {}) or {}
        if sym not in orchs:
            await self._reply(chat_id, f"❌ Оркестратор для <code>{html.escape(sym)}</code> не найден")
            return
        self._chat_symbol[chat_id] = sym
        await self._reply(chat_id, f"✅ Установлен текущий символ: <code>{html.escape(sym)}</code>")

    async def _cmd_status(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"❌ нет оркестратора для <code>{html.escape(symbol)}</code>")
            return
        st = orch.status()
        started = "🟢" if st.get("started") else "⚪"
        paused = "⏸" if st.get("paused") else "▶️"
        lines = [f"{started} <b>Status</b> {paused} <code>{html.escape(symbol)}</code>"]
        loops = st.get("loops", {})
        for name, info in loops.items():
            mark = "✅" if info.get("task_alive") else "—"
            lines.append(f"{mark} {name} (int={info.get('interval_sec')}, enabled={info.get('enabled')})")
        await self._reply(chat_id, "\n".join(lines))

    async def _cmd_pause(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"❌ нет оркестратора для <code>{html.escape(symbol)}</code>")
            return
        await orch.pause()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_resume(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"❌ нет оркестратора для <code>{html.escape(symbol)}</code>")
            return
        await orch.resume()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_stop(self, chat_id: int, symbol: str) -> None:
        orch = self._get_orchestrator(symbol)
        if not orch:
            await self._reply(chat_id, f"❌ нет оркестратора для <code>{html.escape(symbol)}</code>")
            return
        await orch.stop()
        await self._cmd_status(chat_id, symbol)

    async def _cmd_limits(self, chat_id: int) -> None:
        risk = getattr(self._container, "risk", None)
        cfg = getattr(risk, "config", None)
        if not cfg:
            await self._reply(chat_id, "❌ RiskConfig недоступен")
            return
        txt = (
            "🧰 <b>Лимиты</b>\n"
            f"cooldown: <code>{getattr(cfg, 'cooldown_sec', 0)}s</code>\n"
            f"max_spread: <code>{getattr(cfg, 'max_spread_pct', 0)}</code>%\n"
            f"max_position_base: <code>{getattr(cfg, 'max_position_base', 0)}</code>\n"
            f"max_orders/hour: <code>{getattr(cfg, 'max_orders_per_hour', 0)}</code>\n"
            f"daily_loss_limit_quote: <code>{getattr(cfg, 'daily_loss_limit_quote', 0)}</code>\n"
            f"max_fee_pct: <code>{getattr(cfg, 'max_fee_pct', 0)}</code>%  slippage: <code>{getattr(cfg, 'max_slippage_pct', 0)}</code>%\n"
        )
        await self._reply(chat_id, txt)

    async def _cmd_risk(self, chat_id: int, symbol: str) -> None:
        # легкая оценка загрузки лимитов: что найдём — покажем
        parts = ["📏 <b>Риск (оценка)</b>"]
        st = getattr(self._container, "storage", None)
        cfg = getattr(getattr(self._container, "risk", None), "config", None)

        # дневной оборот/убыток — если есть методы
        try:
            if st and hasattr(st, "trades"):
                if hasattr(st.trades, "daily_turnover_quote"):
                    tq = st.trades.daily_turnover_quote(symbol)
                    parts.append(f"turnover_today: <code>{tq}</code>")
        except Exception:
            _log.error("risk_calc_turnover_failed", exc_info=True)

        try:
            if cfg and getattr(cfg, "max_orders_per_hour", 0):
                if hasattr(st.trades, "count_orders_last_minutes"):
                    cnt = st.trades.count_orders_last_minutes(symbol, 60)
                    mx = getattr(cfg, "max_orders_per_hour", 0)
                    parts.append(f"orders_60m: <code>{cnt}/{mx}</code>")
        except Exception:
            _log.error("risk_calc_orders_failed", exc_info=True)

        await self._reply(chat_id, "\n".join(parts))

    async def _cmd_balance(self, chat_id: int, symbol: str) -> None:
        broker = getattr(self._container, "broker", None)
        if not broker:
            await self._reply(chat_id, "❌ broker недоступен")
            return
        base, quote = _split_symbol(symbol)
        try:
            b = await broker.fetch_balance()
            getv = lambda cur: b.get(cur, {}) if isinstance(b, dict) else getattr(b, cur.lower(), {})
            base_free = getv(base).get("free") or getv(base).get("total") or "0"
            quote_free = getv(quote).get("free") or getv(quote).get("total") or "0"
            await self._reply(chat_id, f"👛 <b>Баланс</b> <code>{html.escape(symbol)}</code>\n"
                                       f"{base}: <code>{base_free}</code>\n{quote}: <code>{quote_free}</code>")
        except Exception:
            _log.error("balance_fetch_failed", exc_info=True)
            await self._reply(chat_id, "❌ не удалось получить баланс")

    async def _cmd_position(self, chat_id: int, symbol: str) -> None:
        st = getattr(self._container, "storage", None)
        if not st:
            await self._reply(chat_id, "❌ storage недоступен")
            return
        try:
            pos_repo = getattr(st, "positions", None)
            pos = pos_repo.get(symbol) if pos_repo else None
            if not pos:
                await self._reply(chat_id, f"— позиций по <code>{html.escape(symbol)}</code> нет")
                return
            base_qty = getattr(pos, "base_qty", None) or pos.get("base_qty")
            avg_price = getattr(pos, "avg_price", None) or pos.get("avg_price")
            await self._reply(chat_id, f"📌 <b>Позиция</b> <code>{html.escape(symbol)}</code>\n"
                                       f"base_qty: <code>{base_qty}</code>\navg_price: <code>{avg_price}</code>")
        except Exception:
            _log.error("position_read_failed", exc_info=True)
            await self._reply(chat_id, "❌ ошибка чтения позиции")

    async def _cmd_today(self, chat_id: int, symbol: str) -> None:
        st = getattr(self._container, "storage", None)
        if not st:
            await self._reply(chat_id, "❌ storage недоступен")
            return
        try:
            parts = [f"📅 <b>Сегодня</b> <code>{html.escape(symbol)}</code>"]
            if hasattr(st.trades, "daily_turnover_quote"):
                t = st.trades.daily_turnover_quote(symbol)
                parts.append(f"turnover_quote: <code>{t}</code>")
            if hasattr(st.trades, "count_orders_last_minutes"):
                c60 = st.trades.count_orders_last_minutes(symbol, 60)
                c5 = st.trades.count_orders_last_minutes(symbol, 5)
                parts.append(f"orders_60m: <code>{c60}</code> | 5m: <code>{c5}</code>")
            await self._reply(chat_id, "\n".join(parts))
        except Exception:
            _log.error("today_stats_failed", exc_info=True)
            await self._reply(chat_id, "❌ ошибка статистики")

    async def _cmd_pnl(self, chat_id: int, symbol: str) -> None:
        st = getattr(self._container, "storage", None)
        try:
            if st and hasattr(st.trades, "pnl_today_quote"):
                v = st.trades.pnl_today_quote(symbol)
                await self._reply(chat_id, f"💰 <b>PNL</b> сегодня <code>{html.escape(symbol)}</code>: <code>{v}</code>")
                return
        except Exception:
            _log.error("pnl_today_failed", exc_info=True)
        await self._reply(chat_id, "ℹ️ PnL сегодня: <code>N/A</code> (нет агрегатора)")

    async def _cmd_stats(self, chat_id: int, symbol: str) -> None:
        # тонкий placeholder, т.к. агрегаторов может не быть
        await self._reply(chat_id, "ℹ️ Статистика 7d: <code>N/A</code>")

    async def _cmd_health(self, chat_id: int, symbol: str) -> None:
        # Отдаём быструю эвристику: ping storage/broker/bus в рантайме здесь не дублируем.
        await self._reply(chat_id, "❤️ <b>Health</b>: используется периодическая проверка внутри бота\n"
                                   "Если будут проблемы — придёт алёрт (broker.error / dms).")

    async def run(self) -> None:
        if not self._token:
            _log.info("tg_bot_disabled_no_token")
            return
        _log.info("tg_bot_started")

        while True:
            try:
                data = await self._get_updates()
                if not data.get("ok"):
                    await asyncio.sleep(1.0)
                    continue
                for upd in data.get("result", []):
                    self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat = msg.get("chat", {})
                    chat_id = int(chat.get("id", 0))
                    from_user = msg.get("from", {})
                    user_id = int(from_user.get("id", 0))
                    text = (msg.get("text") or "").strip()

                    if not text.startswith("/"):
                        continue
                    if not self._allow(user_id):
                        await self._reply(chat_id, "⛔ Доступ запрещён")
                        continue

                    cmd = text.split()[0].lower()

                    # --- маршрутизация команд ---
                    if cmd in ("/help", "/start"):
                        await self._cmd_help(chat_id)
                        continue
                    if cmd == "/symbols":
                        await self._cmd_symbols(chat_id)
                        continue
                    if cmd == "/set":
                        await self._cmd_set(chat_id, text)
                        continue

                    sym = self._pick_symbol(chat_id, text)

                    if cmd == "/status":
                        await self._cmd_status(chat_id, sym); continue
                    if cmd == "/pause":
                        await self._cmd_pause(chat_id, sym); continue
                    if cmd == "/resume":
                        await self._cmd_resume(chat_id, sym); continue
                    if cmd == "/stop":
                        await self._cmd_stop(chat_id, sym); continue
                    if cmd == "/limits":
                        await self._cmd_limits(chat_id); continue
                    if cmd == "/risk":
                        await self._cmd_risk(chat_id, sym); continue
                    if cmd == "/balance":
                        await self._cmd_balance(chat_id, sym); continue
                    if cmd == "/position":
                        await self._cmd_position(chat_id, sym); continue
                    if cmd == "/today":
                        await self._cmd_today(chat_id, sym); continue
                    if cmd == "/pnl":
                        await self._cmd_pnl(chat_id, sym); continue
                    if cmd == "/stats":
                        await self._cmd_stats(chat_id, sym); continue
                    if cmd == "/health":
                        await self._cmd_health(chat_id, sym); continue

                    await self._reply(chat_id, "🤖 Неизвестная команда. /help")
            except asyncio.CancelledError:
                break
            except Exception:
                _log.error("tg_bot_loop_failed", exc_info=True)
                await asyncio.sleep(1.0)
