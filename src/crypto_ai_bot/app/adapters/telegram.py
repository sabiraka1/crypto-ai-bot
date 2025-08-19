# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

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
        "/start — приветствие\n"
        "/help — помощь\n"
        "/status — состояние бота\n"
        "/profit [SYMBOL] — сводка PnL по закрытым сделкам\n"
        "/positions — открытые позиции\n"
    )


def _json_from_bytes(body: bytes) -> Dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def _pnl_summary(trades_repo: Any, symbol: Optional[str]) -> Dict[str, float]:
    """
    Единый источник PnL — репозиторий сделок.
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
    Без внешних зависимостей: urllib. Блокирующую отправку уводим в отдельный поток.
    """
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token)}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    def _do():
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning("telegram sendMessage failed: %r", e)
        return False


def _settings_from(app_or_container: Any) -> Any:
    # допускаем как app.state.container.settings, так и container.settings
    if app_or_container is None:
        return None
    st = getattr(app_or_container, "settings", None)
    if st is not None:  # container
        return st
    # app
    state = getattr(app_or_container, "state", None)
    if state is not None:
        cont = getattr(state, "container", None)
        if cont is not None:
            return getattr(cont, "settings", None)
    return None


def _container_and_settings(app: Any, container: Any) -> Tuple[Any, Any]:
    if container is not None:
        return container, _settings_from(container)
    # fallback: попробовать достать из app
    cont = None
    if app is not None:
        cont = getattr(getattr(app, "state", None), "container", None)
    return cont, _settings_from(cont)


# ---------- внутренняя реализация ----------

async def _handle_update_impl(app: Any, container: Any, payload: Dict[str, Any]) -> JSONResponse:
    container, settings = _container_and_settings(app, container)
    if settings is None or not getattr(settings, "TELEGRAM_BOT_TOKEN", None):
        return JSONResponse({"ok": False, "error": "telegram_not_configured"})

    msg = (payload.get("message") or payload.get("edited_message") or {})
    chat = msg.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    text = str(msg.get("text") or "").strip()

    if not chat_id or not text:
        return JSONResponse({"ok": True, "result": "noop"})

    # ---- routing ----
    if text.startswith("/start"):
        return JSONResponse(_make_reply(chat_id, "Привет! Я бот crypto-ai-bot.\nНапиши /help."))

    if text.startswith("/help"):
        return JSONResponse(_make_reply(chat_id, _help_text()))

    if text.startswith("/status"):
        try:
            sym = normalize_symbol(getattr(settings, "SYMBOL", "BTC/USDT"))
            timeframe = getattr(settings, "TIMEFRAME", "15m")
            bus_h = container.bus.health() if hasattr(container.bus, "health") else {"running": True}
            pending = container.trades_repo.count_pending() if hasattr(container.trades_repo, "count_pending") else 0
            exits = 0
            if hasattr(container.exits_repo, "count_active"):
                exits = int(container.exits_repo.count_active(symbol=sym))
            resp = (
                f"mode: {getattr(settings, 'MODE', 'paper')}\n"
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
            sym = normalize_symbol(parts[1]) if len(parts) > 1 else normalize_symbol(getattr(settings, "SYMBOL", "BTC/USDT"))
            summary = _pnl_summary(container.trades_repo, sym)
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
            sym = normalize_symbol(getattr(settings, "SYMBOL", "BTC/USDT"))
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


# ---------- универсальная обёртка (совместима с обеими сигнатурами) ----------

async def handle_update(*args, **kwargs) -> JSONResponse:
    """
    Поддерживает 2 сигнатуры:
      1) handle_update(app, raw_body_bytes, container)
      2) handle_update(container, parsed_payload_dict)
    """
    # вариант 1
    if len(args) == 3:
        app, raw_body, container = args
        payload = _json_from_bytes(raw_body) if isinstance(raw_body, (bytes, bytearray)) else {}
        return await _handle_update_impl(app, container, payload)

    # вариант 2
    if len(args) == 2:
        container, payload = args
        app = getattr(container, "app", None) or getattr(container, "application", None)
        if not isinstance(payload, dict):
            try:
                payload = dict(payload)
            except Exception:
                payload = {}
        return await _handle_update_impl(app, container, payload)

    return JSONResponse({"ok": False, "error": "bad_handler_signature"})


# ---------- alerts ----------

async def send_alert(app_or_container: Any, text: str, chat_id: Optional[int] = None) -> bool:
    """
    Отправка аварийного уведомления.
    Принимает либо app (FastAPI), либо container.
    Если chat_id не указан — берёт TELEGRAM_ALERT_CHAT_ID из настроек.
    """
    settings = _settings_from(app_or_container)
    if settings is None:
        logger.warning("send_alert: settings not found")
        return False

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token:
        logger.warning("send_alert: TELEGRAM_BOT_TOKEN is not set")
        return False

    target = chat_id or getattr(settings, "TELEGRAM_ALERT_CHAT_ID", None)
    if not target:
        logger.warning("send_alert: chat_id not provided and TELEGRAM_ALERT_CHAT_ID not set")
        return False

    try:
        target = int(target)
    except Exception:
        logger.warning("send_alert: invalid chat_id %r", target)
        return False

    return await _telegram_send_message(token, target, text)
