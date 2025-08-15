
# src/crypto_ai_bot/telegram/handler.py
from __future__ import annotations

"""
Telegram webhook utilities:
- set_webhook / delete_webhook / get_webhook_info
- validate_secret_header
- dispatch_update: safely calls telegram.bot.process_update (sync or async)

This module is the single, canonical handler for Telegram HTTP integration.
"""

import inspect
from typing import Any, Dict, Mapping, Tuple

import anyio
import requests

# Your main bot-side update handler (must exist)
from crypto_ai_bot.telegram.bot import process_update  # noqa: F401


# --- Webhook management -------------------------------------------------------
def set_webhook(
    bot_token: str,
    webhook_url: str,
    secret_token: str = "",
    drop_pending: bool = True,
    timeout: float = 10.0,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Registers a Telegram webhook for the given bot token.
    Returns (ok, response_json).
    """
    params: Dict[str, Any] = {"url": webhook_url}
    if secret_token:
        params["secret_token"] = secret_token
    if drop_pending:
        params["drop_pending_updates"] = True

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        r = requests.post(url, params=params, timeout=timeout)
        data = r.json()
        return bool(data.get("ok")), data
    except Exception as e:
        return False, {"ok": False, "error": repr(e)}


def delete_webhook(
    bot_token: str,
    drop_pending: bool = True,
    timeout: float = 10.0,
) -> Tuple[bool, Dict[str, Any]]:
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    params = {"drop_pending_updates": True} if drop_pending else {}
    try:
        r = requests.post(url, params=params, timeout=timeout)
        data = r.json()
        return bool(data.get("ok")), data
    except Exception as e:
        return False, {"ok": False, "error": repr(e)}


def get_webhook_info(
    bot_token: str, timeout: float = 10.0
) -> Tuple[bool, Dict[str, Any]]:
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        r = requests.get(url, timeout=timeout)
        data = r.json()
        return bool(data.get("ok")), data
    except Exception as e:
        return False, {"ok": False, "error": repr(e)}


# --- Secret header validation -------------------------------------------------
def validate_secret_header(headers: Mapping[str, str], expected: str) -> bool:
    """
    Validates Telegram's X-Telegram-Bot-Api-Secret-Token header.
    """
    if not expected:
        return False
    got = headers.get("X-Telegram-Bot-Api-Secret-Token") or headers.get(
        "x-telegram-bot-api-secret-token"
    )
    return got == expected


# --- Safe dispatcher (sync/async compatible) ---------------------------------
async def dispatch_update(payload: Dict[str, Any]) -> None:
    """
    Dispatches an incoming Telegram update to crypto_ai_bot.telegram.bot.process_update.
    If process_update is async â€” simply await it.
    If it is sync â€” offload to a worker thread to avoid blocking the event loop.
    """
    if inspect.iscoroutinefunction(process_update):  # type: ignore[arg-type]
        await process_update(payload)  # type: ignore[misc]
    else:
        await anyio.to_thread.run_sync(process_update, payload)

