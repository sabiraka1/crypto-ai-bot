from __future__ import annotations
from typing import Any, Dict
import asyncio
import html
import os
import time
from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.utils.http_client import aget  # для getUpdates
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical

def _getv(d: Any) -> Any:  # Исправлено: добавлен возвращаемый тип
    def _inner(k: str) -> Any:
        if isinstance(d, dict):
            return d.get(k, {})
        try:
            return getattr(d, k.lower(), {})
        except Exception:
            return {}
    return _inner

_log = get_logger("adapters.telegram_bot")

_TTL = float(os.environ.get("TELEGRAM_BOT_TTL_SECS", "30") or 30.0)
_THR = os.environ.get("TELEGRAM_BOT_THROTTLE", "3/5")
try:
    _THR_N, _THR_WIN = [int(x) for x in _THR.split("/", 1)]
except Exception:  # fallback
    _THR_N, _THR_WIN = 3, 5


def _split_symbol(sym: str) -> tuple[str, str]:
    try:
        b, q = sym.split("/", 1)
        return b.upper(), q.upper()
    except Exception:
        return sym.upper(), ""


class TelegramBotCommands:
    """
    Long-poll командный бот.
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
        self._allowed = set(int(x) for x in allowed_users if str(x).strip())
        self._container = container
        self._alerts = TelegramAlerts(bot_token=bot_token, chat_id="")  # укажем chat_id в send()
        self._default_symbol = canonical(default_symbol)
        self._offset = 0
        self._lp_sec = max(3, int(long_poll_sec))
        self._chat_symbol: dict[int, str] = {}  # chat_id -> symbol
        self._cache: dict[tuple[int, str], tuple[float, str]] = {}  # (chat,cmd) -> (ts, text)
        self._recent: dict[int, list[float]] = {}  # user_id -> ts[]

    # --------------------- утилиты ---------------------

    def _allow(self, user_id: int | None) -> bool:
        if not self._allowed:
            return True
        try:
            return int(user_id or 0) in self._allowed
        except Exception:
            return False

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

    async def _get_updates(self) -> Dict[str, Any]:  # Исправлено: dict -> Dict
        try:
            params = {"timeout": self._lp_sec, "offset": self._offset}
            resp = await aget(self._endpoint("getUpdates"), params=params, timeout=self._lp_sec + 5)
            if resp.status_code != 200:
                _log.warning("tg_get_updates_non_200", extra={"status": resp.status_code})
                return {"ok": False, "result": []}
            return resp.json()  # Это уже возвращает Dict[str, Any]
        except Exception:
            _log.error("tg_get_updates_failed", exc_info=True)
            return {"ok": False, "result": []}

    # ... остальной код без изменений, кроме типов

    async def _cmd_risk(self, chat_id: int, symbol: str) -> None:
        parts = ["🔍 <b>Риск (оценка)</b>"]
        st = getattr(self._container, "storage", None)
        cfg = getattr(getattr(self._container, "risk", None), "config", None)
        try:
            if st and hasattr(st, "trades") and hasattr(st.trades, "daily_turnover_quote"):
                tq = st.trades.daily_turnover_quote(symbol)
                parts.append(f"turnover_today: <code>{tq}</code>")
        except Exception:
            _log.error("risk_calc_turnover_failed", exc_info=True)

        try:
            if cfg and getattr(cfg, "max_orders_per_hour", 0) and st and hasattr(st, "trades") and hasattr(st.trades, "count_orders_last_minutes"):
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
            gv = _getv(b)
            base, quote = (symbol.split('/') + ['',''])[:2]
            base_free = gv(base).get('free') or gv(base).get('total') or '0'
            quote_free = gv(quote).get('free') or gv(quote).get('total') or '0'
            await self._reply(chat_id, f"💛 <b>Баланс</b> <code>{html.escape(symbol)}</code>\n"
                                           f"{base}: <code>{base_free}</code>\n{quote}: <code>{quote_free}</code>")
        except Exception:
            await self._reply(chat_id, "⚠️ Не удалось получить баланс")

    # --------------------- главный метод run() ---------------------
    
    async def run(self) -> None:
        """Главный цикл long-polling для получения команд из Telegram"""
        _log.info("telegram_bot_commands_started")
        
        while True:
            try:
                # Получаем обновления от Telegram
                data = await self._get_updates()
                
                if data.get("ok"):
                    for update in data.get("result", []):
                        # Обновляем offset для следующего запроса
                        self._offset = update.get("update_id", 0) + 1
                        
                        # Обрабатываем сообщение
                        msg = update.get("message", {})
                        if not msg:
                            continue
                            
                        user_id = msg.get("from", {}).get("id")
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "").strip()
                        
                        if not text or not chat_id:
                            continue
                        
                        # Проверяем доступ
                        if not self._allow(user_id):
                            await self._reply(chat_id, "❌ Доступ запрещен")
                            continue
                        
                        # Проверяем rate limit
                        if not self._throttle(user_id):
                            await self._reply(chat_id, "⚠️ Слишком много запросов, подождите")
                            continue
                        
                        # Обрабатываем команды
                        if text.startswith("/"):
                            cmd = text.split()[0].lower()
                            
                            # Команды без символа
                            if cmd == "/help":
                                await self._cmd_help(chat_id)
                            elif cmd == "/symbols":
                                await self._cmd_symbols(chat_id)
                            elif cmd == "/set":
                                await self._cmd_set(chat_id, text)
                            elif cmd == "/limits":
                                await self._cmd_limits(chat_id)
                            # Команды с символом
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
                                # Можно добавить другие команды по необходимости
                
                # Небольшая пауза между запросами
                await asyncio.sleep(1)
                
            except Exception:
                _log.error("telegram_bot_run_error", exc_info=True)
                # При ошибке делаем паузу подольше
                await asyncio.sleep(5)