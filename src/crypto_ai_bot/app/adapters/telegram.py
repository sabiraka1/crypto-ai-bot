
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe


_CMD_RE = re.compile(r"^\s*/(\w+)(?:\s+(.*))?$")


async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """Тонкий адаптер Telegram → use-cases через Bot.
    Никакой бизнес-логики и прямого доступа к брокеру/БД.
    """
    text = (
        update.get("message", {}).get("text")
        or update.get("edited_message", {}).get("text")
        or ""
    )
    m = _CMD_RE.match(text)
    if not m:
        return {"ok": True, "reply": "Команда не распознана. /start, /status, /buy, /sell, /why"}

    cmd, args = m.group(1), (m.group(2) or "").strip()

    if cmd == "start":
        return {"ok": True, "reply": "Бот запущен. Команды: /status, /buy <size>, /sell <size>, /why"}

    if cmd == "status":
        st = bot.get_status()
        return {"ok": True, "reply": f"Mode={st['mode']}, {st['symbol']} @ {st['timeframe']}"}

    if cmd in ("buy", "sell"):
        side = "buy" if cmd == "buy" else "sell"
        size = Decimal("0")
        # формат: "/buy 0.01 BTC/USDT 1h"
        parts = args.split()
        if parts:
            try:
                size = Decimal(parts[0])
            except Exception:
                pass

        symbol = cfg.SYMBOL
        timeframe = cfg.TIMEFRAME
        if len(parts) >= 2:
            symbol = parts[1]
        if len(parts) >= 3:
            timeframe = parts[2]

        sym = normalize_symbol(symbol)
        tf = normalize_timeframe(timeframe)

        decision = {
            "action": side,
            "size": str(size),
            "sl": None,
            "tp": None,
            "trail": None,
            "score": 0.5,
        }
        res = bot.execute(decision)
        return {"ok": True, "reply": f"{side.upper()} {sym} size={size} → {res.get('status','ok')}"}

    if cmd == "why":
        # просто проксируем evaluate, где policy возвращает explain
        dec = bot.evaluate()
        exp = dec.get("explain", {})
        return {"ok": True, "reply": f"Score={dec.get('score')}\nExplain keys: {', '.join(exp.keys())}"}

    return {"ok": True, "reply": "Неизвестная команда."}
