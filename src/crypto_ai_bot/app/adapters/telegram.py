# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils.time import now_ms, monotonic_ms
from crypto_ai_bot.utils import metrics as m
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
    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
        return
    except Exception:  # pragma: no cover
        pass
    import urllib.request
    def _post() -> None:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as _:
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
    lines = []
    score = explain.get("score")
    if isinstance(score, (int, float)):
        lines.append(f"score: {score:.4f}")
    elif score is not None:
        lines.append(f"score: {score}")

    votes = explain.get("votes")
    if isinstance(votes, dict) and votes:
        vv = ", ".join(f"{k}={v}" for k, v in votes.items())
        lines.append(f"votes: {vv}")

    parts = explain.get("parts") or explain.get("weights") or {}
    if isinstance(parts, dict) and parts:
        top = sorted(parts.items(), key=lambda kv: abs(kv[1]) if isinstance(kv[1], (int, float)) else 0.0, reverse=True)[:5]
        pretty = ", ".join(f"{k}={v:.3f}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in top)
        lines.append(f"top parts: {pretty}")

    reason = explain.get("reason") or explain.get("why")
    if reason:
        lines.append(f"reason: {reason}")

    return "\n".join(lines) if lines else "no explanation details"

def _parse_eval_args(text: str, default_symbol: str) -> Tuple[str, Optional[str], Optional[int]]:
    tokens = text.split()
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

def _pnl_summary_str(container, symbol: Optional[str]) -> str:
    """
    Пытаемся вытащить PnL через репозиторий трейдов.
    Ищем один из методов:
      - realized_pnl_summary(symbol=None)
      - pnl_summary(symbol=None)
      - get_pnl_summary(symbol=None)
    Если ничего нет — 'n/a'.
    """
    tr = getattr(container.repos, "trades", None)
    if not tr:
        return "pnl: n/a"
    for name in ("realized_pnl_summary", "pnl_summary", "get_pnl_summary"):
        fn = getattr(tr, name, None)
        if callable(fn):
            try:
                summ = fn(symbol=symbol) if "symbol" in getattr(fn, "__code__", type("", (), {"co_varnames": ()})) .co_varnames else fn()  # type: ignore
                if isinstance(summ, dict):
                    # ожидаем поля: realized, fees, count, win, loss, period и т.п.
                    realized = summ.get("realized") or summ.get("realized_usd") or summ.get("pnl")
                    count = summ.get("count") or summ.get("trades")
                    return f"pnl: {realized} (trades: {count})"
                return f"pnl: {summ}"
            except Exception:
                break
    return "pnl: n/a"

# ============================== public API ==================================

async def handle_update(container, payload: Dict[str, Any]) -> None:
    """
    await handle_update(container, payload)
    Команды:
      /start
      /status                       — лёгкий статус + PnL summary
      /eval [SYMBOL] [TF] [LIMIT]   — dry-run (метрики latency)
      /why  [SYMBOL] [TF] [LIMIT]   — объяснение (метрики latency)
    """
    settings = container.settings
    # секрет можно проверять в роуте; если сюда прокинут, тоже учитываем
    configured = getattr(settings, "TELEGRAM_BOT_SECRET", None)
    got = (payload.get("secret") or payload.get("query_secret"))
    if configured and got and configured != got:
        return  # тихо игнорируем

    chat_id, text = _chat_and_text(payload)
    if not chat_id:
        logger.info("telegram_update_without_chat")
        return
    if not text:
        await _reply(container, chat_id, "Empty message")
        return

    lowered = text.strip().lower()

    if lowered.startswith("/start"):
        await _reply(container, chat_id, "Hi! I am your crypto bot.\nUse /status, /eval, /why")
        return

    if lowered.startswith("/status"):
        syms = getattr(settings, "SYMBOLS", None)
        symbol = ", ".join(syms) if syms else getattr(settings, "SYMBOL", "BTC/USDT")
        mode = getattr(settings, "MODE", "paper")
        hb = None
        try:
            hb = getattr(container.repos.kv, "get", lambda *_: None)("orchestrator_heartbeat_ms")
        except Exception:
            hb = None
        pnl_str = _pnl_summary_str(container, None if isinstance(symbol, str) and "," in symbol else (symbol if isinstance(symbol, str) else None))
        msg = f"mode: {mode}\nsymbols: {symbol}\nheartbeat_ms: {hb}\n{pnl_str}"
        await _reply(container, chat_id, msg)
        return

    if lowered.startswith("/eval"):
        symbol, tf, limit = _parse_eval_args(text, getattr(settings, "SYMBOL", "BTC/USDT"))
        with m.timer("telegram_eval_latency_ms", labels={"symbol": str(symbol)}):
            try:
                feat = build_features(symbol, cfg=settings, broker=container.broker,
                                      positions_repo=container.repos.positions, external=container.external)
                decision, explain = decide_policy(symbol, feat, cfg=settings), {}
                if isinstance(decision, tuple) and len(decision) == 2:
                    decision, explain = decision  # type: ignore
                msg = f"*EVAL* `{symbol}`\n\ndecision: `{decision}`\n{_format_explain(explain)}"
                await _reply(container, chat_id, msg, parse_mode="Markdown")
                m.inc("telegram_eval_total", {"symbol": str(symbol), "result": "ok"})
            except Exception as e:
                logger.exception("telegram_eval_failed")
                await _reply(container, chat_id, f"eval failed: {e}")
                m.inc("telegram_eval_total", {"symbol": str(symbol), "result": "error"})
        return

    if lowered.startswith("/why"):
        symbol, tf, limit = _parse_eval_args(text, getattr(settings, "SYMBOL", "BTC/USDT"))
        with m.timer("telegram_why_latency_ms", labels={"symbol": str(symbol)}):
            try:
                feat = build_features(symbol, cfg=settings, broker=container.broker,
                                      positions_repo=container.repos.positions, external=container.external)
                _dec = decide_policy(symbol, feat, cfg=settings)
                explain = {}
                if isinstance(_dec, tuple) and len(_dec) == 2:
                    _, explain = _dec  # type: ignore
                msg = f"*WHY* `{symbol}`\n\n{_format_explain(explain)}"
                await _reply(container, chat_id, msg, parse_mode="Markdown")
                m.inc("telegram_why_total", {"symbol": str(symbol), "result": "ok"})
            except Exception as e:
                logger.exception("telegram_why_failed")
                await _reply(container, chat_id, f"why failed: {e}")
                m.inc("telegram_why_total", {"symbol": str(symbol), "result": "error"})
        return

    await _reply(container, chat_id, "Unknown command. Try /status, /eval, /why")
