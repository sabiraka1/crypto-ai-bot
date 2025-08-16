from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.positions.tracker import build_context
from crypto_ai_bot.core.risk import manager as risk_manager

def _fmt_pct(x) -> str:
    try:
        return f"{float(x):.2f}%"
    except Exception:
        return "n/a"

def _fmt_usd(x) -> str:
    try:
        return f"${float(x):.2f}"
    except Exception:
        return "n/a"

def handle_update(update: Dict[str, Any], cfg, broker, **repos) -> Dict[str, Any]:
    """
    Минимальный Telegram-адаптер с командами:
     - /status — сводка (exposure/dd/seq_losses/price/spread) + решение + risk verdict/limits
     - /audit [N] — последние N записей "decision" (если audit_repo настроен)
    """
    message = (update or {}).get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")

    if not text.startswith("/"):
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd in ("/status", "/s"):
        summary = build_context(cfg, broker, positions_repo=repos.get("positions_repo"), trades_repo=repos.get("trades_repo"))
        risk_ok, risk_reason = risk_manager.check(summary, cfg)

        dec = evaluate(cfg, broker, symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=300, **repos)
        lines = [
            f"SYMBOL: {cfg.SYMBOL}  TF: {cfg.TIMEFRAME}",
            f"PRICE: {_fmt_usd(summary.get('price'))}  SPREAD: {_fmt_pct(summary.get('spread_pct'))}",
            f"EXPOSURE: {_fmt_usd(summary.get('exposure_usd'))} ({_fmt_pct(summary.get('exposure_pct'))})",
            f"DAY DD: {_fmt_pct(summary.get('day_drawdown_pct'))}  SEQ LOSSES: {summary.get('seq_losses')}",
            f"DECISION: {dec.get('action')}  SCORE: {dec.get('score'):.3f}",
            f"RISK: {'OK' if risk_ok else 'BLOCKED'}  REASON: {risk_reason or '-'}",
        ]
        return {"ok": True, "chat_id": chat_id, "text": "\n".join(lines)}

    if cmd.startswith("/audit"):
        try:
            n = int(parts[1]) if len(parts) > 1 else 5
        except Exception:
            n = 5
        audit = repos.get("audit_repo")
        if audit is None:
            return {"ok": True, "chat_id": chat_id, "text": "Audit not configured."}
        items = audit.list_by_type("decision", n)
        if not items:
            return {"ok": True, "chat_id": chat_id, "text": "No recent decisions."}
        lines = ["Last decisions:"]
        for it in items:
            p = it.get("payload") or {}
            dec = p.get("decision") or {}
            lines.append(f"• id={it.get('id')} action={dec.get('action')} score={dec.get('score')}")
        return {"ok": True, "chat_id": chat_id, "text": "\n".join(lines)}

    return {"ok": True, "chat_id": chat_id, "text": "Unknown command."}
