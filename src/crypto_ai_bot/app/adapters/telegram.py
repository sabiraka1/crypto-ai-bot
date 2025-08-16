from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.core.positions.tracker import build_context

HELP = (
    "Команды:\n"
    "/start — приветствие\n"
    "/status — текущее состояние и оценка риска\n"
    "/tick — только оценка (без исполнения)\n"
    "/execute — оценка + исполнение (если риск разрешит)\n"
    "/why — объяснение решения и причин блокировки\n"
    "/help — показать это сообщение\n"
)

def _arg_after(cmd: str, text: str) -> str:
    # Возвращает аргументы после команды, если есть
    try:
        if not text.startswith(cmd):
            return ""
        rest = text[len(cmd):].strip()
        return rest
    except Exception:
        return ""

def _parse_symbol_timeframe(args: str, cfg) -> tuple[str, str]:
    # Простейший парсер "<SYMBOL> <TF>"
    parts = [p for p in (args or "").replace(",", " ").split() if p]
    symbol = parts[0] if parts else cfg.SYMBOL
    timeframe = parts[1] if len(parts) > 1 else cfg.TIMEFRAME
    return symbol, timeframe

def handle_update(update: Dict[str, Any], cfg, broker, **repos) -> Dict[str, Any]:
    """
    Тонкий адаптер Telegram → core.use_cases.*
    Возвращает dict, который app.server отдаёт как JSON.
    """
    text = ""
    try:
        message = update.get("message") or update.get("edited_message") or {}
        text = str(message.get("text", "")).strip()
    except Exception:
        text = ""

    if not text or text == "/help":
        return {"ok": True, "text": HELP}

    if text == "/start":
        return {"ok": True, "text": "Привет! Я готов работать. Введите /help чтобы увидеть команды."}

    if text.startswith("/status"):
        args = _arg_after("/status", text)
        symbol, timeframe = _parse_symbol_timeframe(args, cfg)

        summary = build_context(cfg, broker,
                                positions_repo=repos.get("positions_repo"),
                                trades_repo=repos.get("trades_repo"))
        ok, reason = risk_manager.check(summary, cfg)
        return {
            "ok": True,
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "risk": {"ok": bool(ok), "reason": reason},
            "summary": summary,
        }

    if text.startswith("/tick"):
        args = _arg_after("/tick", text)
        symbol, timeframe = _parse_symbol_timeframe(args, cfg)
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=300, **repos)
        return {"ok": True, "status": "evaluated", "symbol": symbol, "timeframe": timeframe, "decision": dec}

    if text.startswith("/execute"):
        args = _arg_after("/execute", text)
        symbol, timeframe = _parse_symbol_timeframe(args, cfg)
        res = eval_and_execute(cfg, broker, symbol=symbol, timeframe=timeframe, limit=300, **repos)
        return {"ok": True, **res}

    if text.startswith("/why"):
        args = _arg_after("/why", text)
        symbol, timeframe = _parse_symbol_timeframe(args, cfg)

        summary = build_context(cfg, broker,
                                positions_repo=repos.get("positions_repo"),
                                trades_repo=repos.get("trades_repo"))
        ok, reason = risk_manager.check(summary, cfg)
        dec = evaluate(cfg, broker, symbol=symbol, timeframe=timeframe, limit=300,
                       risk_reason=(None if ok else reason), **repos)
        explain = dec.get("explain", {})
        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "risk": {"ok": bool(ok), "reason": reason},
            "explain": explain,
            "score": dec.get("score"),
            "action": dec.get("action"),
        }

    # неизвестная команда — подсказка
    return {"ok": False, "error": "unknown_command", "text": HELP}
