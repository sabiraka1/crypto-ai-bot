# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

# Мягкие зависимости — чтобы не ломать в отсутствии модулей
try:
    from crypto_ai_bot.core.use_cases.evaluate import evaluate
except Exception:
    evaluate = None  # type: ignore

def _text(update: Dict[str, Any]) -> str:
    return str((((update or {}).get("message") or {}).get("text")) or "").strip()

def _reply(text: str) -> Dict[str, Any]:
    # сервер вернёт этот JSON как webhook-ответ (у тебя так уже сделано)
    return {"ok": True, "text": text}

def _parse_size(s: str) -> Optional[str]:
    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if not m:
        return None
    val = m.group(1).replace(",", ".")
    try:
        Decimal(val)
        return val
    except Exception:
        return None

def handle_update(update: Dict[str, Any], cfg: Any, broker: Any, http: Any, *, bus: Optional[Any] = None) -> Dict[str, Any]:
    """
    Поддерживаем базовые команды:
      /start, /status, /eval, /why
    + Новые (п.7): /buy [qty], /sell [qty]
      — публикуем событие ManualTradeRequested в шину (без прямого вызова place_order),
        чтобы не требовать repos в адаптере и не ломать контракт.
    """
    txt = _text(update).lower()

    if txt.startswith("/start"):
        return _reply("Привет! Я бот. Доступно: /status, /eval, /why, /buy <qty>, /sell <qty>")

    if txt.startswith("/status"):
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")
        mode = getattr(cfg, "MODE", "paper")
        return _reply(f"MODE={mode}; SYMBOL={sym}; TF={tf}")

    if txt.startswith("/eval"):
        if evaluate is None:
            return _reply("Оценка недоступна.")
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")
        limit = int(getattr(cfg, "LIMIT_BARS", 300) or 300)
        try:
            d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            act = str(d.get("action", "hold"))
            sc = d.get("score_blended") or d.get("score") or d.get("score_base")
            return _reply(f"Decision: {act} (score={sc})")
        except Exception as e:
            return _reply(f"Ошибка eval: {type(e).__name__}: {e}")

    if txt.startswith("/why"):
        if evaluate is None:
            return _reply("Объяснение недоступно.")
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")
        limit = int(getattr(cfg, "LIMIT_BARS", 300) or 300)
        try:
            d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            exp = d.get("explain", {})
            return _reply(f"Explain: {exp}")
        except Exception as e:
            return _reply(f"Ошибка explain: {type(e).__name__}: {e}")

    # --- Новое: ручные команды /buy /sell ---
    if txt.startswith("/buy") or txt.startswith("/sell"):
        side = "buy" if txt.startswith("/buy") else "sell"
        qty = _parse_size(txt) or getattr(cfg, "POSITION_SIZE", "0.00")
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")

        evt = {
            "type": "ManualTradeRequested",
            "ts_ms": int(time.time() * 1000),
            "symbol": sym,
            "timeframe": tf,
            "side": side,
            "qty": str(qty),
        }
        published = False
        if bus is not None:
            try:
                bus.publish(evt)
                published = True
            except Exception:
                published = False

        metrics.inc("telegram_manual_trade_total", {"side": side, "published": "1" if published else "0"})
        if published:
            return _reply(f"Запрос на ручную сделку отправлен в очередь: {side} {qty} {sym}")
        return _reply("Не удалось отправить запрос: шина недоступна.")

    return _reply("Неизвестная команда. Доступно: /status, /eval, /why, /buy <qty>, /sell <qty>")
