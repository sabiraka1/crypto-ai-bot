# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe


@dataclass
class _Args:
    cmd: str
    symbol: str | None = None
    timeframe: str | None = None
    size: float | None = None


def _parse_cmd(text: str) -> _Args:
    if not text:
        return _Args(cmd="help")
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower()
    rest = parts[1:]
    args = _Args(cmd=cmd)

    if cmd in {"eval", "evaluate", "why"}:
        # /eval BTCUSDT 1h | /why BTCUSDT 1h
        if rest:
            args.symbol = rest[0]
        if len(rest) > 1:
            args.timeframe = rest[1]
    elif cmd in {"buy", "sell"}:
        # /buy BTCUSDT 0.01
        if rest:
            args.symbol = rest[0]
        if len(rest) > 1:
            try:
                args.size = float(rest[1])
            except Exception:
                args.size = None
    else:
        args.cmd = "help"
    return args


def _fmt_explain(decision: Dict[str, Any]) -> str:
    ex = decision.get("explain") or {}
    m = ex.get("market") or {}
    ind = ex.get("indicators") or {}
    sc = (ex.get("scores") or {})
    risk = ex.get("risk") or {}
    lines = [
        f"📊 {m.get('symbol','?')} {m.get('timeframe','?')} @ {m.get('price','?')} (ts={m.get('ts','?')})",
        f"– ema20/ema50: {ind.get('ema20')} / {ind.get('ema50')}",
        f"– rsi14: {ind.get('rsi14')}, macd_hist: {ind.get('macd_hist')}, atr%: {ind.get('atr_pct')}",
        f"– scores → rule={sc.get('rule_score')}, ai={sc.get('ai_score')}, final={sc.get('final')}",
        f"– thresholds → buy≥{(sc.get('thresholds') or {}).get('buy')}, sell≤{(sc.get('thresholds') or {}).get('sell')}",
        f"– risk → ok={risk.get('ok')} reason={risk.get('reason')}",
    ]
    return "\n".join(lines)


async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """
    Тонкий адаптер: парсит текст, нормализует symbol/timeframe и вызывает публичные методы бота.
    """
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    args = _parse_cmd(text)

    if args.cmd == "help":
        return {"chat_id": chat_id, "text": "Команды:\n/eval SYMBOL TF\n/why SYMBOL TF\n/buy SYMBOL SIZE\n/sell SYMBOL SIZE"}

    if args.symbol:
        try:
            args.symbol = normalize_symbol(args.symbol)
        except Exception as e:
            return {"chat_id": chat_id, "text": f"Неверный символ: {e}"}

    if args.timeframe:
        try:
            args.timeframe = normalize_timeframe(args.timeframe)
        except Exception as e:
            return {"chat_id": chat_id, "text": f"Неверный таймфрейм: {e}"}

    # дефолты из конфигурации
    sym = args.symbol or cfg.SYMBOL
    tf = args.timeframe or cfg.TIMEFRAME

    if args.cmd in {"eval", "evaluate"}:
        decision = bot.evaluate(symbol=sym, timeframe=tf, limit=cfg.FEATURE_LIMIT)
        if isinstance(decision, dict) and "explain" in decision:
            pretty = _fmt_explain(decision)
            return {"chat_id": chat_id, "text": f"Decision: {decision.get('action')} (score={decision.get('score')})\n\n{pretty}"}
        return {"chat_id": chat_id, "text": f"Decision: {decision}"}

    if args.cmd == "why":
        decision = bot.evaluate(symbol=sym, timeframe=tf, limit=cfg.FEATURE_LIMIT)
        pretty = _fmt_explain(decision if isinstance(decision, dict) else {})
        return {"chat_id": chat_id, "text": f"🤖 Почему так?\n{pretty}"}

    if args.cmd in {"buy", "sell"}:
        if args.size is None or args.size <= 0:
            return {"chat_id": chat_id, "text": "Формат: /buy SYMBOL SIZE (SIZE>0)"}
        decision = {"action": args.cmd, "symbol": sym, "timeframe": tf, "size": args.size}
        result = bot.execute(decision)
        return {"chat_id": chat_id, "text": f"Order result: {result}"}

    return {"chat_id": chat_id, "text": "Неизвестная команда. /help"}
