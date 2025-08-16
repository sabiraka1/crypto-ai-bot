from __future__ import annotations
from typing import Dict, Any
from decimal import Decimal

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.use_cases.get_stats import get_stats as uc_get_stats

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

def _parse_days(text: str) -> int:
    parts = text.strip().split()
    if len(parts) < 2:
        return 1
    tok = parts[1].lower()
    if tok.endswith('d'):
        tok = tok[:-1]
    try:
        d = int(tok)
        return max(1, min(365, d))
    except Exception:
        return 1

async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    message = (update or {}).get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    symbol = cfg.SYMBOL
    timeframe = cfg.TIMEFRAME
    limit = 300

    if text.startswith("/start"):
        reply = "Команды: /status, /why, /stats [Nd], /buy <s> (dev), /sell <s> (dev)"
        return {"chat_id": chat_id, "text": reply}

    if text.startswith("/status"):
        d = uc_evaluate(cfg, bot, symbol=symbol, timeframe=timeframe, limit=limit)
        reply = f"status: {d.get('action')} score={d.get('score')}\n{_fmt_explain(d)}"
        return {"chat_id": chat_id, "text": reply}

    if text.startswith("/why"):
        d = uc_evaluate(cfg, bot, symbol=symbol, timeframe=timeframe, limit=limit)
        reply = "WHY:\n" + _fmt_explain(d)
        return {"chat_id": chat_id, "text": reply}

    if text.startswith("/stats"):
        days = _parse_days(text)
        s = uc_get_stats(cfg, bot, positions_repo=None, trades_repo=None, symbol=symbol, window_days=days)
        exp = s.get("exposure_value", "0")
        pnl_u = s.get("pnl_unrealized", "0")
        pnl_r = s.get("realized_pnl_window", "0")
        cnt = s.get("positions_open", 0)
        trades = s.get("trades_window_count", 0)
        top = s.get("top_symbols", [])
        top_s = ", ".join(f"{t['symbol']}:{t['exposure']}" for t in top) if top else "-"
        reply = f"stats({days}d): pos={cnt}, exposure={exp}, pnl_unreal={pnl_u}, pnl_realized={pnl_r}, trades={trades}\nTOP: {top_s}"
        return {"chat_id": chat_id, "text": reply}

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
        action = "buy" if text.startswith("/buy") else "sell"
        res = uc_eval_and_execute(
            cfg, bot, symbol=symbol, timeframe=timeframe, limit=1,
            positions_repo=None, trades_repo=None, audit_repo=None, uow=None, idempotency_repo=None,
        )
        return {"chat_id": chat_id, "text": f"dev {action} {amt}: {res.get('status')}"}

    return {"chat_id": chat_id, "text": "Неизвестная команда. Есть: /status, /why, /stats [Nd], /buy <s> (dev), /sell <s> (dev)"} 
