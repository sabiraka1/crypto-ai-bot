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

    if cmd in {"eval", "evaluate"}:
        # /eval BTCUSDT 1h
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


async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """
    Тонкий адаптер: парсит текст, нормализует symbol/timeframe и вызывает публичные методы бота.
    Никаких индикаторов/репозиториев/брокеров напрямую.
    """
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    args = _parse_cmd(text)

    if args.cmd == "help":
        return {"chat_id": chat_id, "t
