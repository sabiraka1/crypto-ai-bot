from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.utils.http_client import get_http_client


@dataclass
class Args:
    symbol: str
    timeframe: str
    limit: int = 300
    size: Optional[str] = None


def _parse_symbol_timeframe(text: str, cfg) -> Args:
    # Примеры: "/why BTC/USDT 1h", "/status", "/buy 0.01"
    parts = text.strip().split()
    symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
    timeframe = getattr(cfg, "TIMEFRAME", "1h")
    size = None

    for p in parts[1:]:
        if "/" in p or "-" in p:
            symbol = p
        elif p.lower().endswith(("m", "h", "d")):
            timeframe = p
        else:
            size = p

    return Args(
        symbol=normalize_symbol(symbol),
        timeframe=normalize_timeframe(timeframe),
        limit=int(getattr(cfg, "BUILD_LIMIT", 300)),
        size=size,
    )


def _format_explain(decision: Dict[str, Any]) -> str:
    ex = decision.get("explain", {})
    signals = ex.get("signals", {})
    blocks = ex.get("blocks", {})
    weights = ex.get("weights", {})
    th = ex.get("thresholds", {})
    ctx = ex.get("context", {})

    top = []
    for key in ("ema20", "ema50", "rsi", "macd_hist", "atr", "atr_pct"):
        if key in signals:
            top.append(f"{key}: {signals[key]}")

    risk_block = blocks.get("risk", {})
    risk_line = "OK" if risk_block.get("ok") else f"BLOCKED: {risk_block.get('reason', 'n/a')}"

    lines = [
        f"Action: *{decision.get('action', 'hold').upper()}*   Score: *{decision.get('score', 0):.3f}*",
        f"Symbol: {ctx.get('symbol','?')}  TF: {ctx.get('timeframe','?')}",
        "",
        "*Signals*:",
        ("; ".join(top) or "—"),
        "",
        "*Risk*: " + risk_line,
        "",
        "*Weights*: rule={weights[rule]:.2f} ai={weights[ai]:.2f}".format(weights=weights),
        "*Thresholds*: buy={buy:.2f} sell={sell:.2f} hold_band=±{hold:.2f}".format(
            buy=th.get("buy", 0.55), sell=th.get("sell", 0.45), hold=th.get("hold_band", 0.04)
        ),
    ]
    return "\n".join(lines)


async def handle_update(update: dict, cfg, bot, http=None) -> dict:
    """
    Тонкий адаптер: парсим команды, вызываем use-cases.
    """
    http = http or get_http_client()

    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    if not text:
        return {"ok": True}

    if text.startswith("/start"):
        body = "Привет! Доступно: /status, /why [SYMBOL] [TF], /buy SIZE, /sell SIZE"
    elif text.startswith("/status"):
        body = "✅ Бот запущен. Попробуй /why BTC/USDT 1h"
    elif text.startswith("/why"):
        args = _parse_symbol_timeframe(text, cfg)
        decision = evaluate(cfg, broker=bot.broker, symbol=args.symbol, timeframe=args.timeframe, limit=args.limit)
        body = _format_explain(decision if isinstance(decision, dict) else decision.model_dump())  # на всякий
    else:
        body = "Команда не распознана. /why BTC/USDT 1h"

    if chat_id:
        try:
            await http.post_json(
                f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": body, "parse_mode": "Markdown"},
                timeout=5,
            )
        except Exception:
            pass

    return {"ok": True}
