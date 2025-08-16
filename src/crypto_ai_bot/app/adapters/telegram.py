# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.utils import metrics

def _get_chat_and_text(update: Dict[str, Any]) -> Tuple[Optional[int], str]:
    if not update:
        return None, ""
    if "message" in update:
        msg = update["message"]
        return msg.get("chat", {}).get("id"), (msg.get("text") or "")
    if "callback_query" in update:
        cq = update["callback_query"]
        msg = cq.get("message", {})
        return msg.get("chat", {}).get("id"), (cq.get("data") or "")
    return None, ""

def _parse_command(text: str) -> Tuple[str, str]:
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
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    return http.post_json(_reply_url(token, "sendMessage"), json=payload)

def _default_sym_tf(cfg, symbol_arg: Optional[str], tf_arg: Optional[str]) -> Tuple[str, str]:
    sym = normalize_symbol(symbol_arg or getattr(cfg, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe(tf_arg or getattr(cfg, "TIMEFRAME", "1h"))
    return sym, tf

def _format_decision(dec: Dict[str, Any]) -> str:
    act = html.escape(str(dec.get("action", "hold")).upper())
    score = dec.get("score")
    score_txt = f"{float(score):.3f}" if isinstance(score, (int, float)) else "n/a"
    ex = dec.get("explain", {}) or {}
    reason = html.escape(str(ex.get("blocks", {}).get("risk_reason", "")))
    parts = [
        f"<b>Decision:</b> {act}",
        f"<b>Score:</b> {score_txt}",
        f"<b>Risk:</b> {reason or 'ok'}",
    ]
    return "\n".join(parts)

async def handle_update(update: Dict[str, Any], cfg: Any, broker: Any, http) -> Dict[str, Any]:
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
                "Команды:\n"
                "• /status — режим/символ/TF\n"
                "• /decide [SYMBOL] [TF] [LIMIT] — решение без исполнения\n"
                "• /why [SYMBOL] [TF] [LIMIT] — подробный explain\n"
                "• /trade [SYMBOL] [TF] [LIMIT] — решение+исполнение (см. /tick)\n"
            )
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        elif cmd == "status":
            metrics.inc("tg_command_total", {"cmd": "status"})
            sym, tf = _default_sym_tf(cfg, None, None)
            try:
                tkr = broker.fetch_ticker(sym)
                px = float(tkr.get("last") or tkr.get("close") or 0.0)
                px_txt = f"{px:.2f}"
            except Exception:
                px_txt = "n/a"
            msg = f"<b>Status</b>\nMode: <code>{html.escape(getattr(cfg,'MODE','paper'))}</code>\nSymbol: <b>{html.escape(sym)}</b>\nTF: <b>{html.escape(tf)}</b>\nPrice: <b>{px_txt}</b>"
            _send_text(http, token, chat_id, msg, thread_id=thread_id)
            return {"ok": True}

        elif cmd == "decide":
            metrics.inc("tg_command_total", {"cmd": "decide"})
            parts = rest.split()
            sym = parts[0] if len(parts) >= 1 else None
            tf = parts[1] if len(parts) >= 2 else None
            limit = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else int(getattr(cfg, "FEATURE_LIMIT", 300))
            sym, tf = _default_sym_tf(cfg, sym, tf)
            dec = uc_evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            _send_text(http, token, chat_id, _format_decision(dec), thread_id=thread_id)
            return {"ok": True}

        elif cmd == "why":
            metrics.inc("tg_command_total", {"cmd": "why"})
            parts = rest.split()
            sym = parts[0] if len(parts) >= 1 else None
            tf = parts[1] if len(parts) >= 2 else None
            limit = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else int(getattr(cfg, "FEATURE_LIMIT", 300))
            sym, tf = _default_sym_tf(cfg, sym, tf)
            dec = uc_evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            explain = dec.get("explain") or {}
            js = html.escape(json.dumps(explain, ensure_ascii=False, indent=2))
            _send_text(http, token, chat_id, f"<b>Explain</b>\n<code>{js}</code>", thread_id=thread_id)
            return {"ok": True}

        elif cmd == "trade":
            metrics.inc("tg_command_total", {"cmd": "trade"})
            _send_text(http, token, chat_id, "Для реального исполнения используйте HTTP /tick на сервере.", thread_id=thread_id)
            return {"ok": True}

        else:
            metrics.inc("tg_command_total", {"cmd": "unknown"})
            _send_text(http, token, chat_id, "Неизвестная команда. Наберите /help", thread_id=thread_id)
            return {"ok": True}

    except Exception as e:
        metrics.inc("tg_errors_total", {"type": type(e).__name__})
        _send_text(http, token, chat_id, f"Ошибка: <code>{html.escape(str(e))}</code>", thread_id=thread_id)
        return {"ok": False, "error": str(e)}
