from __future__ import annotations

import json
from typing import Any, Dict

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe


def _reply(chat_id: int | str, text: str) -> Dict[str, Any]:
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def _format_explain(explain: Dict[str, Any]) -> str:
    sig = explain.get("signals", {})
    blocks = explain.get("blocks", {})
    weights = explain.get("weights", {})
    thr = explain.get("thresholds", {})
    ctx = explain.get("context", {})

    parts = []
    parts.append("<b>Последнее решение — объяснение</b>")
    parts.append(f"symbol/timeframe: <code>{ctx.get('symbol')}</code> / <code>{ctx.get('timeframe')}</code>")
    parts.append(f"mode: <code>{ctx.get('mode')}</code>")
    parts.append("")
    parts.append("<b>Signals</b>")
    for k in ("ema_fast", "ema_slow", "rsi", "macd", "macd_signal", "macd_hist", "atr", "atr_pct", "price"):
        if k in sig and sig[k] is not None:
            parts.append(f"• {k}: <code>{sig[k]}</code>")
    parts.append("")
    parts.append("<b>Weights</b>")
    parts.append(f"rule={weights.get('rule', 0):.2f}, ai={weights.get('ai', 0):.2f}")
    parts.append("")
    parts.append("<b>Thresholds</b>")
    parts.append(f"entry_min={thr.get('entry_min', 0):.2f}, exit_max={thr.get('exit_max', 0):.2f}, reduce_below={thr.get('reduce_below', 0):.2f}")
    parts.append("")
    parts.append("<b>Blocks</b>")
    parts.append(f"risk: <code>{blocks.get('risk') or 'ok'}</code>; data: <code>{blocks.get('data') or 'ok'}</code>")

    return "\n".join(parts)


async def handle_update(update: Dict[str, Any], cfg: Any, bot: Any, http: Any) -> Dict[str, Any]:
    """
    Тонкий адаптер:
      - /why        → объяснение последнего решения (из policy.get_last_decision)
      - /why_last   → синоним /why
      - /symbol SYMBOL TF → нормализует и подтверждает ввод
      - иначе — краткая подсказка
    Никакой бизнес-логики, ни доступа к брокеру/БД.
    """
    msg = (update.get("message") or update.get("edited_message")) or {}
    chat_id = msg.get("chat", {}).get("id") or msg.get("from", {}).get("id")
    text: str = msg.get("text") or ""

    if not chat_id:
        return {"ok": True}  # некого уведомлять

    tokens = text.strip().split()
    cmd = tokens[0].lower() if tokens else ""

    # /why и /why_last
    if cmd in ("/why", "/why_last"):
        last = policy.get_last_decision()
        if not last:
            return _reply(chat_id, "Пока нет принятых решений в этом процессе. Запусти торговый цикл или вызови /tick.")
        # аккуратно отформатируем
        score = float(last.get("score", 0.0))
        action = last.get("action", "hold")
        explain = last.get("explain", {})
        head = f"<b>Decision</b>: <code>{action}</code>, score=<code>{score:.3f}</code>"
        body = _format_explain(explain)
        return _reply(chat_id, f"{head}\n\n{body}")

    # /symbol <SYMBOL> [TF] — нормализация ввода пользователя (для удобства)
    if cmd == "/symbol":
        if len(tokens) < 2:
            return _reply(chat_id, "Формат: <code>/symbol BTC/USDT 1h</code>")
        sym = normalize_symbol(tokens[1])
        tf = normalize_timeframe(tokens[2]) if len(tokens) > 2 else getattr(cfg, "TIMEFRAME", "1h")
        return _reply(chat_id, f"Нормализовано:\n • symbol = <code>{sym}</code>\n • timeframe = <code>{tf}</code>")

    # help по умолчанию
    help_text = (
        "<b>Команды</b>\n"
        "• /why — показать объяснение последнего решения\n"
        "• /why_last — синоним /why\n"
        "• /symbol SYMBOL [TF] — нормализовать ввод (например, /symbol btcusdt 1h)\n"
    )
    return _reply(chat_id, help_text)
