# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any, Dict, Optional, List, Tuple

from crypto_ai_bot.utils import metrics
# нормализация символов/таймфреймов — единый реестр
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe


def _get_token(cfg: Any) -> Optional[str]:
    return getattr(cfg, "TELEGRAM_BOT_TOKEN", None) or None


def _chat_id_from_update(update: Dict[str, Any]) -> Optional[str]:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    return str(chat.get("id")) if chat.get("id") is not None else None


def _text_from_update(update: Dict[str, Any]) -> str:
    msg = update.get("message") or update.get("edited_message") or {}
    return str(msg.get("text") or "").strip()


def _trim(s: str, limit: int = 3900) -> str:
    s = s.strip()
    if len(s) > limit:
        return s[: limit - 20] + "\n…(truncated)…"
    return s


def _extract_cmd_args(text: str) -> Tuple[str, str]:
    t = (text or "").strip()
    if not t.startswith("/"):
        return ("", "")
    parts = t.split(maxsplit=1)
    cmd = parts[0].split("@", 1)[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return (cmd, rest)


async def _send_text(http: Any, token: str, chat_id: str, text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": _trim(text)}
        http.post_json(url, payload, timeout=3.5)
    except Exception as e:
        # раньше "глотали" исключение — теперь фиксируем метрикой
        metrics.inc("telegram_send_error_total", {"error": type(e).__name__})
        # и даём шанс увидеть в логах
        try:
            from crypto_ai_bot.utils.logging import logger  # lazy импорт
            logger.warning("telegram_send_error: %s", f"{type(e).__name__}: {e}")
        except Exception:
            pass


def _public_base(cfg: Any) -> Optional[str]:
    return getattr(cfg, "PUBLIC_BASE_URL", None) or None


def _build_chart_links(cfg: Any, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, str]:
    base = _public_base(cfg)
    if not base:
        return {}
    q = []
    if symbol:
        q.append(f"symbol={symbol}")
    if timeframe:
        q.append(f"timeframe={timeframe}")
    if limit is not None:
        q.append(f"limit={int(limit)}")
    qs = ("?" + "&".join(q)) if q else ""
    return {
        "test": f"{base}/chart/test{qs}",
        "profit": f"{base}/chart/profit",
    }


def _format_status(cfg: Any, repos: Any, bus: Any) -> str:
    mode = getattr(cfg, "MODE", "paper")
    sym = getattr(cfg, "SYMBOL", "")
    tf = getattr(cfg, "TIMEFRAME", "")
    try:
        opens = repos.positions.get_open() or []
        open_cnt = len(opens)
    except Exception:
        open_cnt = -1
    pnls: List[float] = []
    try:
        if hasattr(repos.trades, "last_closed_pnls"):
            pnls = [float(x) for x in (repos.trades.last_closed_pnls(50) or []) if x is not None]  # type: ignore
    except Exception:
        pnls = []
    eq = sum(pnls) if pnls else 0.0
    wins = sum(1 for x in pnls if x > 0)
    wr = (100.0 * wins / len(pnls)) if pnls else 0.0
    try:
        h = bus.health()
        dlq = int(h.get("dlq_size") or h.get("dlq_len") or 0)
        bus_status = h.get("status", "ok")
    except Exception:
        dlq = -1
        bus_status = "unknown"
    lines = [
        f"Mode: {mode}",
        f"Symbol: {sym}",
        f"Timeframe: {tf}",
        f"Open positions: {open_cnt if open_cnt >= 0 else 'n/a'}",
        f"Closed trades (last N): {len(pnls)} | Win-rate: {wr:.1f}% | Equity: {eq:.4f}",
        f"Bus: {bus_status} | DLQ: {dlq if dlq >= 0 else 'n/a'}",
    ]
    return "\n".join(lines)


def _cmd_help() -> str:
    return _trim(
        "\n".join(
            [
                "Доступные команды:",
                "/start — приветствие и помощь",
                "/help — справка по командам",
                "/status — текущий статус и краткая статистика",
                "/test — мини-график цены и пробный сигнал",
                "/profit — кривая доходности",
                "/eval — расчёт решения (action/score)",
                "/why — объяснение решения (signals/weights/thresholds/context)",
            ]
        )
    )


def _format_explain(explain: Dict[str, Any]) -> str:
    parts: List[str] = []
    if not isinstance(explain, dict):
        return "нет объяснения"
    signals = explain.get("signals") or {}
    weights = explain.get("weights") or {}
    thresholds = explain.get("thresholds") or {}
    ctx = (explain.get("context") or {}).get("ctx") or (explain.get("context") or {})

    if signals:
        sig_line = ", ".join(f"{k}:{float(v):.3f}" for k, v in list(signals.items())[:10])
        parts.append(f"signals: {sig_line}")
    if weights:
        w_line = ", ".join(f"{k}:{float(v):.2f}" for k, v in weights.items())
        parts.append(f"weights: {w_line}")
    if thresholds:
        th_line = ", ".join(f"{k}:{float(v):.2f}" for k, v in thresholds.items())
        parts.append(f"thresholds: {th_line}")
    if isinstance(ctx, dict):
        keys = []
        for k in ("btc_dominance", "fear_greed", "dxy", "exposure_open_positions", "exposure_notional_quote", "time_drift_ms"):
            v = ctx.get(k)
            if v is not None:
                try:
                    keys.append(f"{k}:{float(v):.2f}")
                except Exception:
                    keys.append(f"{k}:{v}")
        if keys:
            parts.append("context: " + ", ".join(keys))

    return "\n".join(parts) or "нет данных"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


async def handle(update: Dict[str, Any], *, cfg: Any, broker: Any, repos: Any, bus: Any, http: Any) -> Dict[str, Any]:
    token = _get_token(cfg)
    chat_id = _chat_id_from_update(update)
    text = _text_from_update(update)
    cmd, args = _extract_cmd_args(text)

    # Нормализуем ввод пользователя единым реестром символов/таймфреймов
    def parse_args(default_symbol: str, default_tf: str, default_limit: int) -> Tuple[str, str, int]:
        sym = default_symbol
        tf = default_tf
        limit = default_limit
        if args:
            parts = args.split()
            if len(parts) >= 1:
                sym = parts[0]
            if len(parts) >= 2:
                tf = parts[1]
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except Exception:
                    pass
        # ЕДИНАЯ нормализация — критичное требование
        sym = normalize_symbol(sym)
        tf = normalize_timeframe(tf)
        return (sym, tf, limit)

    def chart_links(sym: str, tf: str, limit: int) -> Dict[str, str]:
        return _build_chart_links(cfg, symbol=sym, timeframe=tf, limit=limit)

    reply = {"status": "ok"}

    if cmd in ("", "/start", "/help"):
        out = "Привет! Это бот наблюдения за стратегией.\n\n" + _cmd_help()
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    if cmd == "/status":
        out = _format_status(cfg, repos, bus)
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    if cmd == "/test":
        sym, tf, limit = parse_args(getattr(cfg, "SYMBOL", "BTC/USDT"), getattr(cfg, "TIMEFRAME", "1h"), int(getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300))))
        try:
            from crypto_ai_bot.core.use_cases.evaluate import evaluate
            # важное изменение: выносим блокирующий расчёт из event loop
            d = await asyncio.to_thread(evaluate, cfg, broker, symbol=sym, timeframe=tf, limit=limit, repos=repos, http=http)
        except Exception as e:
            d = {"action": "hold", "error": f"{type(e).__name__}: {e}"}
        try:
            t = broker.fetch_ticker(sym)
            price = _safe_float(t.get("last"))
        except Exception:
            price = 0.0
        link = chart_links(sym, tf, limit).get("test")
        lines = [
            f"{sym} {tf}",
            f"price: {price:.4f}" if price else "price: n/a",
            f"action: {d.get('action','hold')} | score: {d.get('score')}",
        ]
        if link:
            lines.append(f"chart: {link}")
        out = "\n".join(lines)
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    if cmd == "/profit":
        link = chart_links(getattr(cfg, "SYMBOL", "BTC/USDT"), getattr(cfg, "TIMEFRAME", "1h"), int(getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300)))).get("profit")
        try:
            if hasattr(repos.trades, "last_closed_pnls"):
                pnls = [float(x) for x in (repos.trades.last_closed_pnls(10000) or []) if x is not None]  # type: ignore
            else:
                pnls = []
        except Exception:
            pnls = []
        eq = sum(pnls) if pnls else 0.0
        out = f"Equity: {eq:.4f}" + (f"\nchart: {link}" if link else "")
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    if cmd == "/eval":
        sym, tf, limit = parse_args(getattr(cfg, "SYMBOL", "BTC/USDT"), getattr(cfg, "TIMEFRAME", "1h"), int(getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300))))
        try:
            from crypto_ai_bot.core.use_cases.evaluate import evaluate
            d = await asyncio.to_thread(evaluate, cfg, broker, symbol=sym, timeframe=tf, limit=limit, repos=repos, http=http)
        except Exception as e:
            d = {"action": "hold", "error": f"{type(e).__name__}: {e}"}
        action = d.get("action", "hold")
        score = d.get("score")
        score_blended = d.get("score_blended", score)
        out = f"{sym} {tf}\naction: {action}\nscore: {score}\nscore_blended: {score_blended}"
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    if cmd == "/why":
        sym, tf, limit = parse_args(getattr(cfg, "SYMBOL", "BTC/USDT"), getattr(cfg, "TIMEFRAME", "1h"), int(getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300))))
        try:
            from crypto_ai_bot.core.use_cases.evaluate import evaluate
            d = await asyncio.to_thread(evaluate, cfg, broker, symbol=sym, timeframe=tf, limit=limit, repos=repos, http=http)
            explain = d.get("explain") or {}
        except Exception as e:
            explain = {"error": f"{type(e).__name__}: {e}"}
        out = f"{sym} {tf}\n" + _format_explain(explain)
        if token and chat_id:
            await _send_text(http, token, chat_id, out)
        return reply

    out = "Неизвестная команда.\n\n" + _cmd_help()
    if token and chat_id:
        await _send_text(http, token, chat_id, out)
    return reply
