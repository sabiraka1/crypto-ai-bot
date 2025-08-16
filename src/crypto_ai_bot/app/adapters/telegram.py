from __future__ import annotations
from typing import Any, Dict, Optional
from decimal import Decimal
import math

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.utils.http_client import get_http_client

HELP = (
    "🤖 *Crypto AI Bot*\n"
    "/start — помощь\n"
    "/status — текущий сигнал (без исполнения)\n"
    "/why — объяснение сигнала (индикаторы/порог/веса/контекст)\n"
    "/audit — последние решения (аудит)\n"
    "\n"
    "Пример: /audit 5"
)

def _fmt_pct(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"{x:.2f}%"

def _fmt_num(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    if abs(x) >= 100:
        return f"{x:,.2f}"
    return f"{x:.6f}".rstrip("0").rstrip(".")

def _pick_text(update: Dict[str, Any]) -> tuple[int, str]:
    msg = (update.get("message") or update.get("edited_message") or {})
    chat = msg.get("chat", {})
    chat_id = chat.get("id", 0)
    text = msg.get("text") or ""
    return int(chat_id), str(text).strip()

def _render_status(decision: Dict[str, Any]) -> str:
    ctx = (decision.get("explain") or {}).get("context") or {}
    ind = (decision.get("explain") or {}).get("signals") or {}
    price = (decision.get("explain") or {}).get("context", {}).get("price")
    return (
        "📈 *Status*\n"
        f"• Action: *{decision.get('action','?').upper()}*\n"
        f"• Score: *{decision.get('score',0):.3f}*\n"
        f"• Price: *{_fmt_num(price)}*\n"
        f"• RSI: {_fmt_num(ind.get('rsi'))} | MACD hist: {_fmt_num(ind.get('macd_hist'))}\n"
        f"• EMA: fast {_fmt_num(ind.get('ema_fast'))} / slow {_fmt_num(ind.get('ema_slow'))}\n"
        f"• ATR%: {_fmt_pct(ind.get('atr_pct'))} | Spread%: {_fmt_pct(ctx.get('spread_pct'))}\n"
    )

def _render_why(decision: Dict[str, Any]) -> str:
    e = decision.get("explain") or {}
    ind = e.get("signals") or {}
    ctx = e.get("context") or {}
    w = e.get("weights") or {}
    thr = e.get("thresholds") or {}
    blocks = e.get("blocks") or {}

    lines = [
        "🧠 *Why?*",
        f"• Action: *{decision.get('action','?').upper()}* | Score: *{decision.get('score',0):.3f}*",
        f"• Weights: rule={w.get('rule',0.5):.2f}, ai={w.get('ai',0.5):.2f}",
        f"• Thresholds: buy={thr.get('buy',0.6):.2f}, sell={thr.get('sell',0.4):.2f}",
        "• Signals:",
        f"    - RSI: {_fmt_num(ind.get('rsi'))}",
        f"    - MACD hist: {_fmt_num(ind.get('macd_hist'))}",
        f"    - EMA fast/slow: {_fmt_num(ind.get('ema_fast'))} / {_fmt_num(ind.get('ema_slow'))}",
        f"    - ATR%: {_fmt_pct(ind.get('atr_pct'))}",
        "• Context:",
        f"    - hour: {ctx.get('hour','—')}  | spread%: {_fmt_pct(ctx.get('spread_pct'))}",
        f"    - exposure%: {_fmt_pct(ctx.get('exposure_pct'))} | exposure$: {_fmt_num(ctx.get('exposure_usd'))}",
        f"    - day_dd%: {_fmt_pct(ctx.get('day_drawdown_pct'))}",
    ]
    if blocks:
        lines.append("• Blocks:")
        for k, v in blocks.items():
            lines.append(f"    - {k}: {v}")
    return "\n".join(lines)

def _render_audit(audit_repo, limit: int = 5) -> str:
    if audit_repo is None:
        return "⚠️ audit_repo не настроен"
    try:
        items = audit_repo.list_by_type("decision", limit) or []
    except Exception as e:
        return f"⚠️ error: {type(e).__name__}: {e}"
    if not items:
        return "Журнал пуст."
    lines = ["🗂 *Audit (последние решения)*"]
    for it in items:
        p = it.get("payload") or {}
        lines.append(
            f"• {it.get('id')} — action={p.get('action')} score={p.get('score')}"
        )
    return "\n".join(lines[:1+limit])

def _send_text(chat_id: int, text: str, cfg) -> Dict[str, Any]:
    token = getattr(cfg, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        http = get_http_client()
        resp = http.post_json(url, json=payload, timeout=10.0)
        return resp or {"ok": False}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

def handle_update(update: Dict[str, Any], cfg, broker, **deps) -> Dict[str, Any]:
    chat_id, text = _pick_text(update)
    if not chat_id:
        return {"ok": False, "error": "no_chat_id"}

    parts = (text or "").split()
    cmd = parts[0].lower() if parts else ""

    if cmd in ("/start", "/help"):
        return _send_text(chat_id, HELP, cfg)

    if cmd == "/status":
        try:
            dec = evaluate(cfg, broker, symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=300, **deps)
            return _send_text(chat_id, _render_status(dec), cfg)
        except Exception as e:
            return _send_text(chat_id, f"⚠️ error: {type(e).__name__}: {e}", cfg)

    if cmd == "/why":
        try:
            dec = evaluate(cfg, broker, symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=300, **deps)
            return _send_text(chat_id, _render_why(dec), cfg)
        except Exception as e:
            return _send_text(chat_id, f"⚠️ error: {type(e).__name__}: {e}", cfg)

    if cmd == "/audit":
        try:
            limit = int(parts[1]) if len(parts) > 1 else 5
        except Exception:
            limit = 5
        return _send_text(chat_id, _render_audit(deps.get("audit_repo"), limit), cfg)

    return _send_text(chat_id, HELP, cfg)
