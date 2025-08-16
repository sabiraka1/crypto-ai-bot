from __future__ import annotations

import json
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute

def _fmt_explain_short(explain: Dict[str, Any]) -> str:
    blocks = explain.get("blocks") or {}
    sigs = explain.get("signals") or {}
    lines = []
    if blocks.get("risk"):
        lines.append(f"🚫 risk: {blocks['risk'].get('reason')}")
    if "rate_limit" in blocks:
        rl = blocks["rate_limit"]
        lines.append(f"⏱ rate_limit {rl.get('key')} ({rl.get('calls')}/{rl.get('per_s')}s)")
    show = []
    for k in ("ema_fast","ema_slow","rsi","macd_hist","atr","atr_pct"):
        if k in sigs:
            try:
                show.append(f"{k}={float(sigs[k]):.4g}")
            except Exception:
                show.append(f"{k}={sigs[k]}")
    if show:
        lines.append("🔎 " + ", ".join(show))
    return "\n".join(lines) if lines else "—"

def _ok(d: Dict[str, Any], key: str) -> bool:
    return key in d and d[key] not in (None, "", 0, "0")

def handle_update(update: Dict[str, Any], cfg, broker, **repos) -> Dict[str, Any]:
    """
    Тонкий адаптер: парсит команды и маршрутизирует в use-cases.
    Поддержка: /start, /status, /why, /tick, /execute
    Возвращает готовый JSON (для FastAPI обработчика).
    """
    text = (update.get("message") or {}).get("text", "").strip()
    if not text:
        return {"ok": True, "text": "empty_message"}

    parts = text.split()
    cmd = parts[0].lower()

    symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
    timeframe = getattr(cfg, "TIMEFRAME", "1h")
    limit = int(getattr(cfg, "DEFAULT_LIMIT", 300))

    if cmd == "/start":
        return {"ok": True, "text": "Hi! Use /status, /why, /tick, /execute"}

    if cmd == "/status":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {
            "ok": True,
            "text": f"symbol={symbol} tf={timeframe}\naction={dec.get('action')} score={dec.get('score')}",
        }

    if cmd == "/why":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        expl = dec.get("explain") or {}
        return {
            "ok": True,
            "text": f"/why for {symbol} {timeframe}\n{_fmt_explain_short(expl)}\nscore={dec.get('score')} action={dec.get('action')}",
            "explain": expl,  # в ответе отдадим полный explain
        }

    if cmd == "/tick":
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, "decision": dec}

    if cmd == "/execute":
        res = eval_and_execute(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"ok": True, **res}

    return {"ok": False, "text": f"unknown command: {cmd}"}
