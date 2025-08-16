from __future__ import annotations
from typing import Dict, Any, Optional
from decimal import Decimal

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

def _fmt_explain(decision: Dict[str, Any]) -> str:
    e = decision.get("explain", {}) or {}
    lines = []
    lines.append(f"score: {decision.get('score')}")
    thr = e.get("thresholds", {})
    if thr:
        lines.append(f"thresholds: buy={thr.get('buy')} sell={thr.get('sell')}")
    sig = e.get("signals", {})
    if sig:
        top = {k: sig[k] for k in list(sig)[:6]}
        lines.append("signals: " + ", ".join(f"{k}={v}" for k,v in top.items()))
    ctx = e.get("context", {})
    if ctx:
        lines.append("ctx: " + ", ".join(f"{k}={v}" for k,v in ctx.items()))
    blk = e.get("blocks", {})
    if blk:
        lines.append("blocks: " + str(blk))
    return "\n".join(lines)

async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """Тонкий адаптер: парсинг команд и вызов use-cases.
    Никакой бизнес-логики.
    Возвращает dict с полями {'chat_id', 'text'} — сервер сам отправит в Telegram API.
    """
    message = (update or {}).get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    # defaults
    symbol = cfg.SYMBOL
    timeframe = cfg.TIMEFRAME
    limit = 300

    if text.startswith("/start"):
        reply = "Привет! Доступные команды: /status, /why, /buy <size> (dev), /sell <size> (dev)"
        return {"chat_id": chat_id, "text": reply}

    if text.startswith("/status"):
        # легкая проверка — просто evaluate без исполнения
        d = uc_evaluate(cfg, bot, symbol=symbol, timeframe=timeframe, limit=limit)
        reply = f"status: {d.get('action')} score={d.get('score')}\n{_fmt_explain(d)}"
        return {"chat_id": chat_id, "text": reply}

    if text.startswith("/why"):
        d = uc_evaluate(cfg, bot, symbol=symbol, timeframe=timeframe, limit=limit)
        reply = "WHY:\n" + _fmt_explain(d)
        return {"chat_id": chat_id, "text": reply}

    # dev-only manual orders (paper/backtest). Пробуем только если не live.
    if text.startswith("/buy") or text.startswith("/sell"):
        if cfg.MODE == "live":
            return {"chat_id": chat_id, "text": "Недоступно в live режиме."}
        parts = text.split()
        if len(parts) < 2:
            return {"chat_id": chat_id, "text": "Укажи размер: /buy 0.01"}
        try:
            amt = Decimal(parts[1])
        except Exception:
            return {"chat_id": chat_id, "text": "Неверный размер. Пример: /buy 0.01"}
        # сформируем подложку решения
        action = "buy" if text.startswith("/buy") else "sell"
        decision = {
            "action": action,
            "size": str(amt if action == "buy" else -amt),
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": 0,
            "decision_id": "manual",
            "explain": {"context": {"source": "telegram_dev"}},
        }
        res = uc_eval_and_execute(
            cfg, bot, symbol=symbol, timeframe=timeframe, limit=1,
            positions_repo=None, trades_repo=None, audit_repo=None, uow=None, idempotency_repo=None,
        )
        # В dev-режиме просто подтверждаем — без настоящего исполнения
        return {"chat_id": chat_id, "text": f"dev {action} {amt}: {res.get('status')}"}

    # fallback
    return {"chat_id": chat_id, "text": "Неизвестная команда. Есть: /status, /why, /buy <s> (dev), /sell <s> (dev)"} 
