# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse

from crypto_ai_bot.core.brokers.symbols import normalize_symbol

logger = logging.getLogger("adapters.telegram")


# ---------- helpers ----------

def _make_reply(chat_id: int, text: str) -> Dict[str, Any]:
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def _help_text() -> str:
    return (
        "Команды:\n"
        "/help — помощь\n"
        "/status — состояние бота\n"
        "/profit [SYMBOL] — сводка PnL по закрытым сделкам\n"
        "/positions — открытые позиции\n"
    )


def _json(body: bytes) -> Dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def _get_pnl_summary(trades_repo: Any, symbol: Optional[str]) -> Dict[str, float]:
    """
    Унифицированный PnL из trades_repo (единый источник правды).
    Ожидаем, что в репозитории есть реализация агрегата.
    """
    try:
        if hasattr(trades_repo, "realized_pnl_summary"):
            return trades_repo.realized_pnl_summary(symbol=symbol)
        if hasattr(trades_repo, "pnl_summary"):
            return trades_repo.pnl_summary(symbol=symbol)
    except Exception as e:
        logger.debug("pnl_summary failed: %r", e)
    return {"closed_trades": 0, "wins": 0, "losses": 0, "pnl_abs": 0.0, "pnl_pct": 0.0}


async def _telegram_send_message(token: str, chat_id: int, text: str) -> bool:
    """
    Без внешних зависимостей (urllib). Блокирующий вызов запускаем в отдельном потоке.
    """
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token)}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode("utf-8")

    def _do():
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning("telegram sendMessage failed: %r", e)
        return False


# ---------- public API ----------

async def handle_update(app, raw_body: bytes, container) -> JSONResponse:
    """
    Принимает webhook update и возвращает JSON с методом Telegram Bot API.
    """
    if not getattr(container.settings, "TELEGRAM_BOT_TOKEN", None):
        return JSONResponse({"ok": False, "error": "telegram_not_configured"})

    upd = _json(raw_body)
    msg = (upd.get("message") or upd.get("edited_message") or {})
    chat = msg.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    text = str(msg.get("text") or "").strip()

    if not chat_id or not text:
        return JSONResponse({"ok": True, "result": "noop"})

    # ---- routing ----
    if text.startswith("/help"):
        return JSONResponse(_make_reply(chat_id, _help_text()))

    if text.startswith("/status"):
        try:
            st = container.settings
            sym = normalize_symbol(getattr(st, "SYMBOL", "BTC/USDT"))
            timeframe = getattr(st, "TIMEFRAME", "15m")
            bus_h = container.bus.health() if hasattr(container.bus, "health") else {"running": True}
            pending = container.trades_repo.count_pending() if hasattr(container.trades_repo, "count_pending") else 0
            exits = 0
            if hasattr(container.exits_repo, "count_active"):
                exits = int(container.exits_repo.count_active(symbol=sym))
            resp = (
                f"mode: {getattr(st, 'MODE', 'paper')}\n"
                f"symbol: {sym}\n"
                f"timeframe: {timeframe}\n"
                f"bus: {bus_h}\n"
                f"pending orders: {pending}\n"
                f"active exits: {exits}"
            )
            return JSONResponse(_make_reply(chat_id, resp))
        except Exception as e:
            return JSONResponse(_make_reply(chat_id, f"Ошибка: {e!r}"))

    if text.startswith("/profit"):
        try:
            parts = text.split()
            sym = normalize_symbol(parts[1]) if len(parts) > 1 else normalize_symbol(getattr(container.settings, "SYMBOL", "BTC/USDT"))
            summary = _get_pnl_summary(container.trades_repo, sym)
            wl = f"{int(summary.get('wins', 0))}/{int(summary.get('losses', 0))}"
            resp = (
                f"{sym}\n"
                f"Closed trades: {int(summary.get('closed_trades', 0))} (W/L {wl})\n"
                f"PnL: {float(summary.get('pnl_abs', 0.0)):.6f} USDT\n"
                f"PnL%: {float(summary.get('pnl_pct', 0.0)):.4f}%"
            )
            return JSONResponse(_make_reply(chat_id, resp))
        except Exception as e:
            return JSONResponse(_make_reply(chat_id, f"Ошибка: {e!r}"))

    if text.startswith("/positions"):
        try:
            sym = normalize_symbol(getattr(container.settings, "SYMBOL", "BTC/USDT"))
            rows = container.positions_repo.get_open() if hasattr(container.positions_repo, "get_open") else []
            if not rows:
                return JSONResponse(_make_reply(chat_id, "Открытых позиций нет"))
            lines = [f"Открытые позиции:"]
            for r in rows:
                if str(r.get("symbol")) != sym:
                    continue
                qty = float(r.get("qty") or 0.0)
                avg = float(r.get("avg_price") or 0.0)
                lines.append(f"{sym}: qty={qty}, avg={avg}")
            return JSONResponse(_make_reply(chat_id, "\n".join(lines)))
        except Exception as e:
            return JSONResponse(_make_reply(chat_id, f"Ошибка: {e!r}"))

    # дефолт
    return JSONResponse(_make_reply(chat_id, "Неизвестная команда. /help"))


async def send_alert(app, text: str, chat_id: Optional[int] = None) -> bool:
    """
    Отправка алерта в Telegram.
    Если chat_id не указан — пытается взять settings.TELEGRAM_ALERT_CHAT_ID (если задан).
    Возвращает True/False по факту попытки.
    """
    try:
        settings = app.state.container.settings
    except Exception:
        logger.warning("send_alert: no settings container found")
        return False

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token:
        logger.warning("send_alert: TELEGRAM_BOT_TOKEN is not set")
        return False

    target = chat_id or getattr(settings, "TELEGRAM_ALERT_CHAT_ID", None)
    if not target:
        logger.warning("send_alert: no chat_id provided and TELEGRAM_ALERT_CHAT_ID not set")
        return False

    try:
        target = int(target)
    except Exception:
        logger.warning("send_alert: invalid chat_id %r", target)
        return False

    return await _telegram_send_message(token, target, text)
