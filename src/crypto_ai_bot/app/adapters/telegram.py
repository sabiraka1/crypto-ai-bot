# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.utils import metrics


# ───────────────────────────── helpers ────────────────────────────────────────

def _get_chat_and_text(update: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """
    Извлекаем chat_id и текст команды из update.
    Поддержка обычных сообщений и callback_query.
    """
    if not update:
        return None, ""

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text") or ""
        return chat_id, text

    if "callback_query" in update:
        cq = update["callback_query"]
        msg = cq.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = cq.get("data") or ""
        return chat_id, text

    return None, ""


def _parse_command(text: str) -> Tuple[str, str]:
    """
    Разбираем строку вида '/cmd arg1 arg2 ...' → ('cmd', 'arg1 arg2 ...')
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return "", ""
    parts = t.split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@", 1)[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return cmd, rest


def _reply_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _send_text(http, token: str, chat_id: int, text: str, *, thread_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Отправляем текстовое сообщение. Только через http_client (никаких requests.*)
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    return http.post_json(_reply_url(token, "sendMessage"), json=payload)


def _format_decision(dec: Dict[str, Any]) -> str:
    act = html.escape(str(dec.get("action", "hold")).upper())
    score = dec.get("score")
    score_txt = f"{float(score):.3f}" if isinstance(score, (int, float)) else "n/a"
    ex = dec.get("explain", {}) or {}
    reason = html.escape(str(ex.get("reason", "")))
    rscore = ex.get("rule_score")
    aiscore = ex.get("ai_score")
    rsi = ex.get("rsi")
    emaf = ex.get("ema_fast")
    emas = ex.get("ema_slow")
    macdh = ex.get("macd_hist")
    atrp = ex.get("atr_pct")
    parts = [
        f"<b>Decision:</b> {act}",
        f"<b>Score:</b> {score_txt}",
    ]
    if reason:
        parts.append(f"<b>Risk:</b> {reason}")
    parts.append("<b>Features:</b>")
    parts.append(f"• rule_score={rscore if rscore is not None else 'n/a'}; ai_score={aiscore if aiscore is not None else 'n/a'}")
    parts.append(f"• RSI={rsi if rsi is not None else 'n/a'}; EMAf={emaf if emaf is not None else 'n/a'}; EMAs={emas if emas is not None else 'n/a'}; MACD_hist={macdh if macdh is not None else 'n/a'}")
    parts.append(f"• ATR%={atrp if atrp is not None else 'n/a'}")
    return "\n".join(parts)


def _default_sym_tf(cfg, symbol_arg: Optional[str], tf_arg: Optional[str]) -> Tuple[str, str]:
    sym = normalize_symbol(symbol_arg or getattr(cfg, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe(tf_arg or getattr(cfg, "TIMEFRAME", "1h"))
    return sym, tf


# ───────────────────────────── команды ───────────────────────────────────────

async def handle_update(update: Dict[str, Any], cfg: Any, broker: Any, http) -> Dict[str, Any]:
    """
    Тонкий Telegram-адаптер:
      - парсит команду
      - нормализует symbol/timeframe
      - вызывает use-cases
      - отправляет ответ через Telegram Bot API
    """
    token = getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    thread_id = getattr(cfg, "TELEGRAM_THREAD_ID", None)
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set in Settings"}

    chat_id, text = _get_chat_and_text(update)
    if not chat_id:
        return {"ok": False, "error": "no_chat_id"}

    cmd, rest = _parse_command(text)

    try:
        if cmd in {"start", "help", ""}:
            metrics.inc("tg_command_total", {"cmd": "start" if cmd != "help" else "help"})
            msg = (
                "<b>Crypto AI Bot</b>\n\n"
                "Доступные команды:\n"
                "• /status — режим, символ, таймфрейм\n"
                "• /decide [SYMBOL] [TF] [LIMIT] — показать решение без исполнения\n"
                "• /trade [SYMBOL] [TF] [LIMIT] — решить и выполнить (paper/backtest)\n"
                "• /help — помощь\n"
            )
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        elif cmd == "status":
            metrics.inc("tg_command_total", {"cmd": "status"})
            sym, tf = _default_sym_tf(cfg, None, None)
            mode = getattr(cfg, "MODE", "paper")
            try:
                tkr = broker.fetch_ticker(sym)
                px = float(tkr.get("last") or tkr.get("close") or 0.0)
                px_txt = f"{px:.2f}"
            except Exception:
                px_txt = "n/a"
            msg = f"<b>Status</b>\nMode: <code>{html.escape(mode)}</code>\nSymbol: <b>{html.escape(sym)}</b>\nTF: <b>{html.escape(tf)}</b>\nPrice: <b>{px_txt}</b>"
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        elif cmd == "decide":
            metrics.inc("tg_command_total", {"cmd": "decide"})
            # разбор аргументов: SYMBOL TF LIMIT
            parts = rest.split()
            sym = parts[0] if len(parts) >= 1 else None
            tf = parts[1] if len(parts) >= 2 else None
            limit = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else int(getattr(cfg, "FEATURE_LIMIT", 300))
            sym, tf = _default_sym_tf(cfg, sym, tf)

            dec = uc_evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            msg = _format_decision(dec)
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        elif cmd == "trade":
            metrics.inc("tg_command_total", {"cmd": "trade"})
            parts = rest.split()
            sym = parts[0] if len(parts) >= 1 else None
            tf = parts[1] if len(parts) >= 2 else None
            limit = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else int(getattr(cfg, "FEATURE_LIMIT", 300))
            sym, tf = _default_sym_tf(cfg, sym, tf)

            res = uc_eval_and_execute(
                cfg,
                broker,
                symbol=sym,
                timeframe=tf,
                limit=limit,
                repos=_make_repos_placeholder(),  # см. комментарий ниже
            )
            # ВНИМАНИЕ: на production сервере /trade лучше вызывать через /tick в app.server,
            # где уже инициализированы реальные repos. Здесь оставляем подсказку.
            msg = "<b>Trade (demo)</b>\nВызов eval_and_execute выполнен. Рекомендуется использовать HTTP /tick на сервере."
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        else:
            metrics.inc("tg_command_total", {"cmd": "unknown"})
            _send_text(http, token, chat_id, "Неизвестная команда. Наберите /help", thread_id=thread_id)
            return {"ok": True}

    except Exception as e:
        metrics.inc("tg_errors_total", {"type": type(e).__name__})
        _send_text(http, token, chat_id, f"Ошибка: <code>{html.escape(str(e))}</code>", thread_id=thread_id)
        return {"ok": False, "error": str(e)}


# ───────────────────────────── заглушка для /trade ────────────────────────────
def _make_repos_placeholder() -> Dict[str, Any]:
    """
    На реальном сервере роут /tick в app.server передаёт настоящие репозитории.
    В Telegram-адаптере оставляем заглушку, чтобы не тянуть БД-слой в app.adapters.
    Если всё же хочешь исполнять сделки прямо из Telegram — перенеси вызов в /tick.
    """
    return {
        "positions": _NoopRepo("positions"),
        "trades": _NoopRepo("trades"),
        "audit": _NoopRepo("audit"),
        "idempotency": _NoopIdemp(),
        "uow": _NoopUOW(),
    }


class _NoopUOW:
    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()


class _NoopRepo:
    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item: str):
        def _noop(*args, **kwargs):
            return None
        return _noop


class _NoopIdemp:
    def claim(self, key: str, ttl_seconds: int) -> bool:
        return True

    def commit(self, key: str) -> None:
        return None

    def release(self, key: str) -> None:
        return None
