from __future__ import annotations

"""
app/adapters/telegram.py — тонкий адаптер.
Разбирает команды, нормализует ввод, делегирует в core.use_cases / bot / policy,
формирует текст ответа без бизнес-логики.
"""

from typing import Any, Dict, Optional

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.utils.charts import plot_candles  # опционально: генерация графиков
from crypto_ai_bot.utils import metrics


def _mk_text_status(status: Dict[str, Any]) -> str:
    dec = status.get("decision") or {}
    ex = dec.get("explain") or {}
    sigs = ex.get("signals") or {}
    th = ex.get("thresholds") or {}
    blocks = ex.get("blocks") or {}
    parts = [
        "📊 *Status*",
        f"*Action*: `{dec.get('action','hold')}`  |  *Score*: `{dec.get('score','-')}`",
        f"*Buy≥*: `{th.get('buy','-')}`  |  *Sell≤*: `{th.get('sell','-')}`",
    ]
    if sigs:
        top = ", ".join(f"{k}={round(v,4)}" for k, v in list(sigs.items())[:6])
        parts.append(f"*Signals*: `{top}`")
    if blocks:
        parts.append(f"⚠️ *Blocks*: `{blocks}`")
    return "\n".join(parts)


async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """
    Возвращает словарь с тем, что надо отправить в Telegram Bot API (sendMessage).
    http — инстанс utils.http_client.HttpClient
    """
    msg = (update.get("message") or update.get("edited_message") or {})
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True, "skip": True}

    parts = text.split()
    cmd, args = parts[0].lower(), parts[1:]

    if cmd in ("/start", "/help"):
        body = (
            "👋 Привет! Доступные команды:\n"
            "/status — текущая оценка рынка\n"
            "/why — подробное объяснение сигнала\n"
            "/buy <size> — рыночная покупка\n"
            "/sell <size> — рыночная продажа\n"
        )
        return {"method": "sendMessage", "chat_id": chat_id, "text": body, "parse_mode": "Markdown"}

    if cmd == "/status":
        dec = uc_evaluate(cfg, bot.broker, symbol=None, timeframe=None, limit=getattr(cfg, "DEFAULT_LIMIT", 300))
        text_out = _mk_text_status({"decision": dec})
        return {"method": "sendMessage", "chat_id": chat_id, "text": text_out, "parse_mode": "Markdown"}

    if cmd == "/why":
        dec = uc_evaluate(cfg, bot.broker, symbol=None, timeframe=None, limit=getattr(cfg, "DEFAULT_LIMIT", 300))
        ex = dec.get("explain") or {}
        # компактный pretty
        sigs = ", ".join(f"{k}={round(v,4)}" for k, v in list((ex.get('signals') or {}).items())[:10])
        blocks = ex.get("blocks") or {}
        body = (
            "🧠 *Why* (объяснение)\n"
            f"*Action*: `{dec.get('action')}` | *Score*: `{round(dec.get('score',0),4)}`\n"
            f"*Thresholds*: `buy≥{ex.get('thresholds',{}).get('buy')}`, `sell≤{ex.get('thresholds',{}).get('sell')}`\n"
            f"*Signals*: `{sigs}`\n"
            f"*Blocks*: `{blocks}`\n"
            f"*Context*: `tf={dec.get('timeframe')}`, `sym={dec.get('symbol')}`"
        )
        return {"method": "sendMessage", "chat_id": chat_id, "text": body, "parse_mode": "Markdown"}

    if cmd in ("/buy", "/sell"):
        if not getattr(cfg, "ENABLE_TRADING", False):
            return {"method": "sendMessage", "chat_id": chat_id, "text": "❌ Trading disabled by config", "parse_mode": "Markdown"}
        size = args[0] if args else str(getattr(cfg, "DEFAULT_ORDER_SIZE", "0.01"))
        decision = {
            "id": f"tg-{cmd[1:]}",
            "action": cmd[1:],
            "size": size,
            "symbol": normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT")),
            "timeframe": normalize_timeframe(getattr(cfg, "TIMEFRAME", "1h")),
            "explain": {
                "context": {"id": "tg-manual", "source": "telegram"},
                "signals": {},
                "blocks": {},
                "weights": {
                    "rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)),
                    "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5)),
                },
                "thresholds": {
                    "buy": float(getattr(cfg, "THRESHOLD_BUY", 0.55)),
                    "sell": float(getattr(cfg, "THRESHOLD_SELL", 0.45)),
                },
            },
        }
        res = place_order(cfg, bot.broker, decision=decision, idem_repo=bot.idem_repo, trades_repo=None, audit_repo=None)
        return {"method": "sendMessage", "chat_id": chat_id, "text": f"Result: `{res}`", "parse_mode": "Markdown"}

    # по умолчанию — help
    return {"method": "sendMessage", "chat_id": chat_id, "text": "Неизвестная команда. Напишите /help", "parse_mode": "Markdown"}
