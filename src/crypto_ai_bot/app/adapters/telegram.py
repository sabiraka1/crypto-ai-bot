# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe

# графики — опционально
try:
    from crypto_ai_bot.utils.charts import plot_candles  # returns PNG bytes
except Exception:
    plot_candles = None  # type: ignore


def _fmt_explain(d: Dict[str, Any]) -> str:
    ex = d.get("explain") or {}
    sig = ex.get("signals") or {}
    blk = ex.get("blocks") or {}
    wts = ex.get("weights") or {}
    thr = ex.get("thresholds") or {}
    lines = [
        f"Decision: {d.get('action')}  size={d.get('size')}  score={round(float(d.get('score') or 0), 3)}",
        f"Signals: ema_fast={sig.get('ema_fast')}  ema_slow={sig.get('ema_slow')}  rsi={sig.get('rsi')}  macd_hist={sig.get('macd_hist')}  atr%={sig.get('atr_pct')}",
        f"Weights: rule={wts.get('rule')}  ai={wts.get('ai')}   Thresholds: buy≥{thr.get('buy')} sell≤{thr.get('sell')}",
    ]
    if blk:
        lines.append(f"Blocks: {', '.join([k for k,v in blk.items() if v])}")
    return "\n".join(lines)


def handle_update(update: Dict[str, Any], cfg, bot, http, *, bus=None) -> Dict[str, Any]:
    """
    Тонкий адаптер Telegram.
    Команды:
      /start
      /status
      /why [SYMBOL] [TF]
      /why_chart [SYMBOL] [TF] — если utils.charts доступен, вернёт картинку.
    """
    msg = (update.get("message") or {}).get("text") or ""
    parts = msg.strip().split()
    cmd = parts[0] if parts else ""

    if cmd == "/start":
        return {"text": "Привет! Команды: /status, /why [SYMBOL] [TF], /why_chart [SYMBOL] [TF]"}

    if cmd == "/status":
        return {"text": f"Mode={cfg.MODE}, Symbol={cfg.SYMBOL}, TF={cfg.TIMEFRAME}, Trading={'ON' if cfg.ENABLE_TRADING else 'OFF'}"}

    if cmd in ("/why", "/why_chart"):
        sym = normalize_symbol(parts[1]) if len(parts) > 1 else cfg.SYMBOL
        tf = normalize_timeframe(parts[2]) if len(parts) > 2 else cfg.TIMEFRAME
        dec = evaluate(cfg, bot, symbol=sym, timeframe=tf, limit=getattr(cfg, "LIMIT_BARS", 300), bus=bus)
        text = _fmt_explain(dec)

        if cmd == "/why_chart" and plot_candles is not None:
            # пробуем получить OHLCV через брокера и нарисовать
            try:
                ohlcv = bot.fetch_ohlcv(sym, tf, limit=int(getattr(cfg, "LIMIT_BARS", 300)))  # broker interface
                # ожидаем формат [[ts, o,h,l,c,v], ...]
                import pandas as pd  # локально в адаптере — только для построения
                df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
                img = plot_candles(df, overlays={"ema20": None, "ema50": None}) if plot_candles else None
                if img:
                    # Телеграм API ждёт multipart/form-data. Мы здесь просто возвращаем «что отправить».
                    return {"text": text, "photo_bytes_b64": base64.b64encode(img).decode("ascii"), "filename": "chart.png"}
            except Exception:
                pass
        return {"text": text}

    return {"text": "Неизвестная команда. Попробуйте: /status, /why, /why_chart"}
