# -*- coding: utf-8 -*-
"""
Minimal Telegram bot interface built on top of unified Settings.
This module exposes a single function:
    process_update(payload: dict) -> None | Awaitable[None]

Supported commands:
  /start, /help, /ping, /status, /version, /config
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

try:
    from crypto_ai_bot.core.settings import Settings  # type: ignore
except Exception:  # pragma: no cover
    from crypto_ai_bot.core.settings import Settings  # type: ignore

from crypto_ai_bot.telegram.handler import tg_send_message

logger = logging.getLogger("crypto_ai_bot.telegram.bot")


def _reply(text: str) -> None:
    ok, resp = tg_send_message(text)
    if not ok:
        logger.warning("tg_send_message failed: %s", resp)


def _help_text(cfg: Settings) -> str:
    return (
        "🤖 *crypto-ai-bot*\n\n"
        "Доступные команды:\n"
        "• /start — краткая справка\n"
        "• /help — список команд\n"
        "• /ping — проверка связи\n"
        "• /status — текущий инструмент/таймфрейм\n"
        "• /version — версия сервера\n"
        "• /config — основные настройки (без секретов)\n"
    )


def _mask(k: str, v: Any) -> Any:
    ks = k.upper()
    if any(s in ks for s in ("SECRET", "TOKEN", "API_KEY", "APIKEY", "PASSWORD")):
        return "***"
    return v


def _config_text(cfg: Settings) -> str:
    try:
        from dataclasses import asdict, is_dataclass

        data = asdict(cfg) if is_dataclass(cfg) else cfg.__dict__
    except Exception:
        data = cfg.__dict__
    parts = [f"*{k}*: `{_mask(k, v)}`" for k, v in data.items()]
    return "⚙️ *Config*\n" + "\n".join(parts[:100])  # ограничим разумно


def _status_text(cfg: Settings) -> str:
    return f"ℹ️ *Status*\nSYMBOL: `{cfg.SYMBOL}`\nTIMEFRAME: `{cfg.TIMEFRAME}`"


def _version_text() -> str:
    return "version: 1.0.0"


def _extract_cmd_and_args(payload: Dict[str, Any]) -> tuple[str, str]:
    text = (
        payload.get("message", {}).get("text")
        or payload.get("edited_message", {}).get("text")
        or ""
    ).strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


def process_update(payload: Dict[str, Any]) -> None | asyncio.Future:
    cfg = Settings.build()
    cmd, args = _extract_cmd_and_args(payload)

    if not cmd:
        # ignore non-commands
        return None

    if cmd in ("/start", "/help"):
        _reply(_help_text(cfg))
        return None

    if cmd == "/ping":
        _reply("pong")
        return None

    if cmd == "/status":
        _reply(_status_text(cfg))
        return None

    if cmd == "/version":
        _reply(_version_text())
        return None

    if cmd == "/config":
        _reply(_config_text(cfg))
        return None

    _reply("Неизвестная команда. Напишите /help")
    return None
