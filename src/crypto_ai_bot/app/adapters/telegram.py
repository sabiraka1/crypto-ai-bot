# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.core.signals._fusion import (  # build/decide допускают **_ignored
    build as build_features,
    decide as decide_policy,
)

logger = logging.getLogger(__name__)

# ============================== helpers =====================================

def _chat_and_text(update: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    return chat_id, text

async def _http_post_json(url: str, payload: Dict[str, Any]) -> None:
    """
    Постим JSON. Предпочитаем httpx, при его отсутствии используем stdlib (в треде).
    Делает best-effort, ошибки логируем — не поднимаем наверх.
    """
    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
        return
    except Exception:  # pragma: no cover
        pass

    # stdlib fallback
    import urllib.request
    import urllib.error

    def _post() -> None:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as _resp:  # noqa: F841
            return

    try:
        await asyncio.to_thread(_post)
    except Exception as e:  # pragma: no cover
        logger.warning("telegram_post_failed: %s", e)

async def _reply(container, chat_id: int, text: str, parse_mode: Optional[str] = None) -> None:
    token = container.settings.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    await _http_post_json(url, payload)

def _format_explain(explain: Dict[str, Any]) -> str:
    # Ожидаем ключи вроде: score, votes, parts/weights, signals и т.п. — формат устойчив к отсутствию полей
    lines = []
    score = explain.get("score")
    if score is not None:
        lines.append(f"score: {score:.4f}" if isinstance(score, (int, float)) else f"score: {score}")

    votes = explain.get("votes")
    if isinstance(votes, dict):
        vv = ", ".join(f"{k}={v}" for k, v in votes.items())
        lines.append(f"votes: {vv}")

    parts = explain.get("parts") or explain.get("weights") or {}
    if isinstance(parts, dict) and parts:
        # берем топ-5 по абсолютному вкладу
        top = sorted(parts.items(), key=lambda kv: abs(kv[1]) if isinstance(kv[1], (int, float)) else 0.0, reverse=True)[:5]
        pretty = ", ".join(f"{k}={v:.3f}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in top)
        lines.append(f"top parts: {pretty}")

    reason = explain.get("reason") or explain.get("why")
    if reason:
        lines.append(f"reason: {reason}")

    if not lines:
        return "no explanation details"
    return "\n".join(lines)

def _parse_eval_args(text: str, default_symbol: str) -> Tuple[str, Optional[str], Optional[int]]:
    # /eval [SYMBOL] [TF] [LIMIT]
    tokens = text.split()
    # tokens[0] == '/eval'
    sym = default_symbol
    tf: Optional[str] = None
    limit: Optional[int] = None
    if len(tokens) >= 2 and not tokens[1].startswith("/"):
        sym = tokens[1]
    if len(tokens) >= 3 and not tokens[2].startswith("/"):
        tf = tokens[2]
    if len(tokens) >= 4 and not tokens[3].startswith("/"):
        try:
            limit = int(tokens[3])
        except ValueError:
            limit = None
    return sym, tf, limit

# ============================== public API ==================================

async def handle_update(container, payload: Dict[str, Any]) -> None:
    """
    Унифицированный хендлер: await handle_update(container, payload)
    Безопасный парс апдейта. Команды:
      /start
      /status
      /eval [SYMBOL] [TF] [LIMIT]  — dry-run, без ордеров
      /why [SYMBOL] [TF] [LIMIT]   — объяснение решения (также dry-run)
    """
    settings = container.settings
    secret_ok = True
    # Если проверка секрета делается здесь (или уже проверена в роуте — ок)
    configured = getattr(settings, "TELEGRAM_BOT_SECRET", None)
    got = (payload.get("secret") or payload.get("query_secret"))  # не из стандартного Telegram, но иногда удобно
    if configured and got and configured != got:
        secret_ok = False

    chat_id, text = _chat_and_text(payload)
    if not chat_id:
        logger.info("telegram_update_without_chat: %s", payload)
        return
    if not secret_ok:
        await _reply(container, chat_id, "forbidden: invalid secret")
        return

    if not text:
        await _reply(container, chat_id, "Empty message")
        return

    lowered = text.strip().lower()

    if lowered.startswith("/start"):
        await _reply(container, chat_id, "Hi! I am your crypto bot.\nUse /status, /eval, /why")
        return

    if lowered.startswith("/status"):
        # очень лёгкий статус без тяжелых вызовов: режим, символы, heartbeat
        syms = getattr(settings, "SYMBOLS", None)
        symbol = ", ".join(syms) if syms else getattr(settings, "SYMBOL", "BTC/USDT")
        hb = None
        try:
            hb = getattr(container.repos.kv, "get", lambda *_: None)("orchestrator_heartbeat_ms")
        except Exception:  # noqa
            hb = None
        mode = getattr(settings, "MODE", "paper")
        await _reply(container, chat_id, f"mode: {mode}\nsymbols: {symbol}\nheartbeat_ms: {hb}")
        return

    if lowered.startswith("/eval"):
        symbol, tf, limit = _parse_eval_args(text, getattr(settings, "SYMBOL", "BTC/USDT"))
        try:
            # dry-run: только построение фич и решение — БЕЗ ордеров
            feat = build_features(symbol, cfg=settings, broker=container.broker,
                                  positions_repo=container.repos.positions, external=container.external)
            decision, explain = decide_policy(symbol, feat, cfg=settings), {}
            # decide_policy может вернуть кортеж или объект — приведём к dict/str
            if isinstance(decision, tuple) and len(decision) == 2:
                decision, explain = decision  # type: ignore
            msg = f"*EVAL* `{symbol}`\n\ndecision: `{decision}`\n{_format_explain(explain)}"
            await _reply(container, chat_id, msg, parse_mode="Markdown")
        except Exception as e:  # noqa
            logger.exception("telegram_eval_failed: %s", e)
            await _reply(container, chat_id, f"eval failed: {e}")
        return

    if lowered.startswith("/why"):
        symbol, tf, limit = _parse_eval_args(text, getattr(settings, "SYMBOL", "BTC/USDT"))
        try:
            # для простоты: считаем актуальное объяснение сейчас
            feat = build_features(symbol, cfg=settings, broker=container.broker,
                                  positions_repo=container.repos.positions, external=container.external)
            _dec = decide_policy(symbol, feat, cfg=settings)
            explain = {}
            if isinstance(_dec, tuple) and len(_dec) == 2:
                _, explain = _dec  # type: ignore
            msg = f"*WHY* `{symbol}`\n\n{_format_explain(explain)}"
            await _reply(container, chat_id, msg, parse_mode="Markdown")
        except Exception as e:  # noqa
            logger.exception("telegram_why_failed: %s", e)
            await _reply(container, chat_id, f"why failed: {e}")
        return

    # default
    await _reply(container, chat_id, "Unknown command. Try /status, /eval, /why")
