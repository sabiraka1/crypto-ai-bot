# -*- coding: utf-8 -*-
"""
Telegram adapter (unified).

- tg_send_message / tg_send_photo: single way to send messages
- process_update(payload): async proxy that delegates to telegram.bot.process_update if present
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("crypto_ai_bot.telegram.handler")

try:
    from crypto_ai_bot.core.settings import Settings  # type: ignore
except Exception:  # pragma: no cover
    from crypto_ai_bot.core.settings import Settings  # type: ignore


def _http_post(url: str, json_payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import requests  # type: ignore

        r = requests.post(url, json=json_payload, timeout=10)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": f"http {r.status_code}", "text": r.text[:200]}
    except Exception:
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(
                url,
                data=json.dumps(json_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                txt = resp.read().decode("utf-8")
                try:
                    return json.loads(txt)
                except Exception:
                    return {"ok": False, "error": f"http {resp.status}", "text": txt[:200]}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "error": str(e)}


def tg_send_message(
    text: str,
    chat_id: Optional[str | int] = None,
    token: Optional[str] = None,
    parse_mode: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any] | str]:
    cfg = Settings.build()
    token = token or getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    chat_id = chat_id or getattr(cfg, "CHAT_ID", None)
    if not token or not chat_id:
        return False, "no token/chat_id"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = _http_post(url, payload)
    return bool(resp.get("ok")), resp


def tg_send_photo(
    image_bytes: bytes,
    caption: Optional[str] = None,
    chat_id: Optional[str | int] = None,
    token: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any] | str]:
    # Fallback implementation using sendDocument with base64 is overkill;
    # keep simple JSON flow by using upload URL if future implementation appears.
    # For now we just send caption text to ensure no crash.
    text = caption or "photo"
    return tg_send_message(text, chat_id=chat_id, token=token)


async def process_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Async proxy to the actual telegram.bot.process_update, if present.
    """
    try:
        from crypto_ai_bot.telegram import bot as tgbot  # type: ignore

        fn = getattr(tgbot, "process_update", None)
        if fn is None:
            logger.debug("telegram.bot.process_update is missing — skip")
            return {"ok": True, "skipped": True}
        res = fn(payload)
        if asyncio.iscoroutine(res):
            await res
        return {"ok": True}
    except Exception as e:  # pragma: no cover
        logger.exception("process_update failed: %s", e)
        return {"ok": False, "error": str(e)}
