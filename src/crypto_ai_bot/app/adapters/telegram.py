from __future__ import annotations

"""
Тонкий адаптер Telegram webhook.

Роль:
- распарсить входящий payload,
- проверить секрет,
- делегировать логику в use_cases,
- отправить ответ пользователю (если есть токен).

❗️ВНИМАНИЕ: НИКАКОЙ бизнес-логики здесь нет.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# --------------------------- helpers ---------------------------

def _chat_and_text(update: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    return chat_id, text


async def _http_post_json(url: str, payload: Dict[str, Any]) -> None:
    # Пытаемся использовать httpx, но не делаем его обязательной зависимостью
    try:  # pragma: no cover
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
        return
    except Exception:
        pass

    # Фоллбэк на стандартную библиотеку (синхронный вызов в thread)
    import urllib.request

    def _post() -> None:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as _:
            return

    try:
        await asyncio.to_thread(_post)
    except Exception as e:  # pragma: no cover
        logger.warning("telegram_post_failed: %s", e)


async def _reply(container, chat_id: int, text: str, parse_mode: Optional[str] = None) -> None:
    token = getattr(container.settings, "TELEGRAM_BOT_TOKEN", None)
    if not token:
        logger.info("telegram_reply_skipped_no_token")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    await _http_post_json(url, payload)


# --------------------------- public API ---------------------------

async def handle_update(container, payload: Dict[str, Any]) -> None:
    """
    Основная точка входа из FastAPI-роута.

    Контракт:
        await handle_update(container, payload)

    Поведение:
    - проверяет секрет, если он задан в settings.TELEGRAM_BOT_SECRET
    - поддерживает базовые команды: /start, /status
    - делегирует оценку в use_cases.evaluate для /eval и объяснение в /why
    """
    settings = container.settings

    # (опц.) защитный секрет — валидация на ровере тоже ок
    configured = getattr(settings, "TELEGRAM_BOT_SECRET", None)
    got = payload.get("secret") or payload.get("query_secret")
    if configured and got and configured != configured:
        return  # тихо игнорируем, без утечек

    chat_id, text = _chat_and_text(payload)
    if not chat_id:
        logger.info("telegram_update_without_chat")
        return

    if not text:
        await _reply(container, chat_id, "Empty message")
        return

    t = text.strip()
    lower = t.lower()

    # Базовые команды
    if lower.startswith("/start"):
        await _reply(
            container,
            chat_id,
            "Hi! I am your crypto bot.\nUse /status, /eval <SYMBOL> [TF], /why <SYMBOL> [TF]",
        )
        return

    if lower.startswith("/status"):
        mode = getattr(settings, "MODE", "paper")
        symbol = getattr(settings, "SYMBOL", "BTC/USDT")
        await _reply(container, chat_id, f"mode: {mode}\nsymbol: {symbol}")
        return

    # Делегирование в use_cases
    if lower.startswith("/eval") or lower.startswith("/why"):
        # Парсим простые аргументы: /eval BTC/USDT 15m
        parts = t.split()
        symbol = parts[1] if len(parts) >= 2 and not parts[1].startswith("/") else getattr(settings, "SYMBOL", "BTC/USDT")
        tf = parts[2] if len(parts) >= 3 and not parts[2].startswith("/") else None

        try:
            from crypto_ai_bot.core.use_cases.evaluate import evaluate  # вызов вашей оценки
        except Exception:
            logger.exception("evaluate_import_failed")
            await _reply(container, chat_id, "evaluation is not available")
            return

        try:
            result = await evaluate(
                cfg=settings,
                broker=container.broker,
                positions_repo=getattr(container, "positions_repo", None),
                symbol=symbol,
                timeframe=tf,
                external={"source": "telegram"},
            )
            # result может быть и просто 'decision', и (decision, explain)
            decision, explain = result, {}
            if isinstance(result, (list, tuple)) and len(result) == 2:
                decision, explain = result  # type: ignore

            # для /why отдаём объяснение; для /eval — кратко
            if lower.startswith("/why"):
                msg = f"*WHY* `{symbol}`\n\n" + json.dumps(explain, ensure_ascii=False, indent=2)
            else:
                msg = f"*EVAL* `{symbol}`\n\ndecision: `{decision}`"

            await _reply(container, chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.exception("telegram_eval_failed")
            await _reply(container, chat_id, f"eval failed: {e}")
        return

    # Фоллбэк
    await _reply(container, chat_id, "Unknown command. Try /status, /eval, /why")
