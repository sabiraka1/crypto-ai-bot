# -*- coding: utf-8 -*-
# см. примечания в шапке файла
from __future__ import annotations

import io
import json
import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import ccxt
except Exception:
    ccxt = None

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.http_client import http_get, http_post

log = logging.getLogger(__name__)

def _is_admin(chat_id: int, cfg: Settings) -> bool:
    if not cfg.ADMIN_CHAT_IDS:
        return False
    ids = {s.strip() for s in str(cfg.ADMIN_CHAT_IDS).split(",") if s.strip()}
    return str(chat_id) in ids

def _api_url(cfg: Settings, method: str) -> str:
    return f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/{method}"

def tg_send_message(chat_id: int, text: str, parse_mode: str = "HTML", cfg: Optional[Settings] = None) -> bool:
    cfg = cfg or Settings.build()
    try:
        url = _api_url(cfg, "sendMessage")
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
        r = http_post(url, json=payload, timeout=10)
        ok = bool(r.ok and r.json().get("ok"))
        if not ok:
            log.warning("tg_send_message failed: %s", r.text)
        return ok
    except Exception as e:
        log.exception("tg_send_message error: %s", e)
        return False

def tg_send_photo(chat_id: int, image_bytes: bytes, caption: Optional[str] = None, cfg: Optional[Settings] = None) -> bool:
    cfg = cfg or Settings.build()
    try:
        url = _api_url(cfg, "sendPhoto")
        files = {"photo": ("chart.png", image_bytes)}
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        r = http_post(url, data=data, files=files, timeout=15)
        ok = bool(r.ok and r.json().get("ok"))
        if not ok:
            log.warning("tg_send_photo failed: %s", r.text)
        return ok
    except Exception as e:
        log.exception("tg_send_photo error: %s", e)
        return False

def _cmd_help(_: Dict[str, Any], cfg: Settings) -> str:
    admin_note = "\n\nАдминские:\n/setwebhook\n/getwebhook\n/delwebhook" if cfg.ADMIN_CHAT_IDS else ""
    return (
        "<b>Доступные команды</b>\n"
        "/help — справка\n"
        "/status — статус и базовые метрики\n"
        "/chart — график OHLCV + краткий обзор\n"
        "/train — обучить модель (заглушка)\n"
        "/errors — хвост логов"
        f"{admin_note}"
    )

def _fetch_ticker_price(cfg: Settings) -> Optional[float]:
    if not ccxt:
        return None
    try:
        ex = getattr(ccxt, cfg.EXCHANGE_NAME)()
        t = ex.fetch_ticker(cfg.SYMBOL)
        return float(t.get("last") or t.get("close") or 0.0) or None
    except Exception as e:
        log.warning("fetch_ticker failed: %s", e)
        return None

def _cmd_status(_: Dict[str, Any], cfg: Settings) -> str:
    price = _fetch_ticker_price(cfg)
    flags = []
    flags.append("SAFE" if cfg.SAFE_MODE else "LIVE")
    flags.append("PAPER" if cfg.PAPER_MODE else "REAL")
    flags.append(f"W:{cfg.WEB_CONCURRENCY}")
    price_txt = f"{price:.2f}" if price is not None else "n/a"
    return (
        f"<b>Status</b>\n"
        f"Symbol: <code>{cfg.SYMBOL}</code>\n"
        f"Timeframe: <code>{cfg.TIMEFRAME}</code>\n"
        f"Price: <b>{price_txt}</b>\n"
        f"Mode: {', '.join(flags)}"
    )

def _fetch_ohlcv(cfg: Settings, limit: int = 120) -> Optional[pd.DataFrame]:
    if not ccxt:
        return None
    try:
        ex = getattr(ccxt, cfg.EXCHANGE_NAME)()
        ohlcv = ex.fetch_ohlcv(cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=limit)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        return df
    except Exception as e:
        log.warning("fetch_ohlcv failed: %s", e)
        return None

def _make_chart(df: pd.DataFrame, title: str = "") -> bytes:
    fig = plt.figure(figsize=(9, 5), dpi=100)
    ax = plt.gca()
    ax.plot(df["ts"], df["close"], linewidth=1.5)
    ax.set_title(title or "Chart")
    ax.set_xlabel("Time")
    ax.set_ylabel("Close")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def _cmd_chart(_: Dict[str, Any], cfg: Settings) -> tuple[Optional[bytes], str]:
    df = _fetch_ohlcv(cfg, limit=150)
    if df is None or df.empty:
        return None, "Не удалось получить данные OHLCV."
    img = _make_chart(df, title=f"{cfg.SYMBOL} • {cfg.TIMEFRAME}")
    last = df.iloc[-1]
    caption = f"<b>{cfg.SYMBOL} • {cfg.TIMEFRAME}</b>\nClose: <b>{last['close']:.2f}</b>  Vol: <code>{int(last['volume'])}</code>"
    return img, caption

def _cmd_train(_: Dict[str, Any], __: Settings) -> str:
    return "🚧 Train: старт обучения (заглушка). Позже свяжем с реальным пайплайном."

def _cmd_errors(_: Dict[str, Any], cfg: Settings) -> str:
    try:
        from pathlib import Path
        logs_dir = Path(cfg.LOGS_DIR or "logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return "Логи не найдены."
        path = files[0]
        tail = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()[-40:]
        txt = "\n".join(tail)
        return f"<b>Последние строки {path.name}</b>\n<code>{txt}</code>"
    except Exception as e:
        log.warning("/errors failed: %s", e)
        return "Не удалось прочитать логи."

def _admin_set_webhook(chat_id: int, cfg: Settings) -> str:
    if not _is_admin(chat_id, cfg):
        return "Недостаточно прав."
    if not cfg.PUBLIC_URL:
        return "PUBLIC_URL не задан."
    url = _api_url(cfg, "setWebhook")
    payload = {"url": f"{cfg.PUBLIC_URL.rstrip('/')}/telegram", "secret_token": cfg.TELEGRAM_SECRET_TOKEN or ""}
    r = http_post(url, json=payload, timeout=10)
    try:
        j = r.json()
    except Exception:
        j = {"ok": False, "raw": r.text}
    ok = j.get("ok", False)
    return f"setWebhook → ok={ok}\n<code>{json.dumps(j, ensure_ascii=False)}</code>"

def _admin_get_webhook(chat_id: int, cfg: Settings) -> str:
    if not _is_admin(chat_id, cfg):
        return "Недостаточно прав."
    url = _api_url(cfg, "getWebhookInfo")
    r = http_get(url, timeout=10)
    try:
        j = r.json()
    except Exception:
        j = {"ok": False, "raw": r.text}
    ok = j.get("ok", False)
    return f"getWebhookInfo → ok={ok}\n<code>{json.dumps(j, ensure_ascii=False)}</code>"

def _admin_del_webhook(chat_id: int, cfg: Settings) -> str:
    if not _is_admin(chat_id, cfg):
        return "Недостаточно прав."
    url = _api_url(cfg, "deleteWebhook")
    r = http_get(url, timeout=10)
    try:
        j = r.json()
    except Exception:
        j = {"ok": False, "raw": r.text}
    ok = j.get("ok", False)
    return f"deleteWebhook → ok={ok}\n<code>{json.dumps(j, ensure_ascii=False)}</code>"

def process_update(payload: Dict[str, Any], cfg: Optional[Settings] = None) -> None:
    cfg = cfg or Settings.build()
    msg = payload.get("message") or payload.get("edited_message")
    if not msg:
        return
    chat_id = int(msg["chat"]["id"])
    text = str(msg.get("text") or "").strip()
    if not text.startswith("/"):
        tg_send_message(chat_id, "Используйте /help для списка команд.", cfg=cfg)
        return
    cmd, *args = text.split()
    cmd = cmd.lower()
    if cmd == "/help":
        tg_send_message(chat_id, _cmd_help(msg, cfg), cfg=cfg); return
    if cmd == "/status":
        tg_send_message(chat_id, _cmd_status(msg, cfg), cfg=cfg); return
    if cmd == "/chart":
        img, cap = _cmd_chart(msg, cfg)
        if img:
            tg_send_photo(chat_id, img, caption=cap, cfg=cfg)
        else:
            tg_send_message(chat_id, cap, cfg=cfg)
        return
    if cmd == "/train":
        tg_send_message(chat_id, _cmd_train(msg, cfg), cfg=cfg); return
    if cmd == "/errors":
        tg_send_message(chat_id, _cmd_errors(msg, cfg), cfg=cfg); return
    if cmd == "/setwebhook":
        tg_send_message(chat_id, _admin_set_webhook(chat_id, cfg), cfg=cfg); return
    if cmd == "/getwebhook":
        tg_send_message(chat_id, _admin_get_webhook(chat_id, cfg), cfg=cfg); return
    if cmd == "/delwebhook":
        tg_send_message(chat_id, _admin_del_webhook(chat_id, cfg), cfg=cfg); return
    tg_send_message(chat_id, "Неизвестная команда. /help", cfg=cfg)
