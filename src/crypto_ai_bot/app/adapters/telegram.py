from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe

def handle_update(update: Dict[str, Any], cfg, broker, **repos) -> Dict[str, Any]:
    """
    Поддержка: /start, /status, /why, /tick, /execute
    Нормализует symbol/timeframe согласно реестру символов.
    """
    text = (update.get("message") or {}).get("text", "").strip()
    if not text:
        return {"ok": True, "text": "empty_message"}

    parts = text.split()
    cmd = parts[0].lower()

    raw_symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
    raw_tf = getattr(cfg, "TIMEFRAME", "1h")
    symbol = normalize_symbol(raw_symbol)
    timeframe = normalize_timeframe(raw_tf)
    limit = int(getattr(cfg, "DEFAULT_LIMIT", 300))

    if cmd == "/start":
        return {"ok": True, "text": "Hi! Use /status, /why, /tick, /execute"}

    if cmd == "/status":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, "text": f"{symbol} {timeframe}: {dec.get('action')} score={dec.get('score')}"}

    if cmd == "/why":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, "decision": dec, "text": f"/why {symbol} {timeframe}"}

    if cmd == "/tick":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, "decision": dec}

    if cmd == "/execute":
        res = eval_and_execute(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, **res}

    return {"ok": False, "text": f"unknown command: {cmd}"}