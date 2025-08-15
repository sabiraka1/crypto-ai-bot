$path = "src\crypto_ai_bot\telegram\bot.py"
New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
Set-Content -Path $path -Encoding UTF8 -Value @'
# Telegram bot adapter (clean, unified).

from __future__ import annotations

import io
import logging
from typing import Optional, Dict, Any, Tuple, List

import numpy as np
import pandas as pd

# Headless backend for servers
import matplotlib
matplotlib.use("Agg")  # type: ignore
import matplotlib.pyplot as plt  # type: ignore

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals.aggregator import aggregate_features
from crypto_ai_bot.utils.http_client import get_http_client

logger = logging.getLogger(__name__)

# ---- module state ----
_cfg: Optional[Settings] = None
_chat_id: Optional[str] = None
_token: Optional[str] = None
_base: Optional[str] = None
_exchange = None   # ccxt-like client injected via set_providers()


# -------- init / DI --------
def init_telegram(cfg: Settings, chat_id: Optional[str] = None) -> None:
    """Initialize token/base/chat from Settings (one time per process)."""
    global _cfg, _chat_id, _token, _base
    _cfg = cfg
    _chat_id = chat_id or cfg.TELEGRAM_CHAT_ID
    _token = cfg.TELEGRAM_BOT_TOKEN
    if not _token:
        logger.warning("Telegram token is empty; sending disabled.")
    _base = f"https://api.telegram.org/bot{_token}" if _token else None
    logger.info("Telegram init: chat=%s", _chat_id)


def set_providers(exchange) -> None:
    """Inject exchange client to allow /status and /chart."""
    global _exchange
    _exchange = exchange


# -------- small helpers --------
def _api_url(method: str) -> str:
    if not _base:
        raise RuntimeError("Telegram is not initialized")
    return f"{_base}/{method}"


def _chunk_text(text: str, limit: int = 4096) -> List[str]:
    return [text[i:i+limit] for i in range(0, len(text), limit)] or [""]


# -------- HTTP wrappers (unified client) --------
def _post_json(url: str, json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    try:
        c = get_http_client()
        resp = c.post_json(url, json=json, timeout=15)
        return bool(resp.get("ok", False)), resp
    except Exception as e:
        logger.exception("Telegram POST failed: %s", e)
        return False, {"ok": False, "error": str(e)}


def _get_json(url: str, params: Dict[str, Any] | None = None) -> Tuple[bool, Dict[str, Any]]:
    try:
        c = get_http_client()
        resp = c.get_json(url, params=params or {}, timeout=15)
        return bool(resp.get("ok", False)), resp
    except Exception as e:
        logger.exception("Telegram GET failed: %s", e)
        return False, {"ok": False, "error": str(e)}


# -------- public senders --------
def tg_send_message(text: str,
                    chat_id: Optional[str] = None,
                    cfg: Optional[Settings] = None) -> Tuple[bool, Dict[str, Any]]:
    cfg = cfg or _cfg
    cid = chat_id or _chat_id or (cfg.TELEGRAM_CHAT_ID if cfg else None)
    if not _token or not _base or not cid:
        logger.warning("tg_send_message skipped: token/base/chat missing")
        return False, {"ok": False, "error": "not-initialized"}

    ok_total = True
    last: Dict[str, Any] = {}
    for chunk in _chunk_text(text):
        ok, resp = _post_json(_api_url("sendMessage"),
                              {"chat_id": cid, "text": chunk, "parse_mode": "HTML"})
        ok_total &= ok
        last = resp
    return ok_total, last


def tg_send_photo(photo_bytes: bytes,
                  caption: str = "",
                  chat_id: Optional[str] = None,
                  cfg: Optional[Settings] = None) -> Tuple[bool, Dict[str, Any]]:
    cfg = cfg or _cfg
    cid = chat_id or _chat_id or (cfg.TELEGRAM_CHAT_ID if cfg else None)
    if not _token or not _base or not cid:
        logger.warning("tg_send_photo skipped: token/base/chat missing")
        return False, {"ok": False, "error": "not-initialized"}

    try:
        c = get_http_client()
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": cid, "caption": caption}
        resp = c.post_multipart(_api_url("sendPhoto"), data=data, files=files, timeout=30)
        return bool(resp.get("ok", False)), resp
    except Exception as e:
        logger.exception("tg_send_photo failed: %s", e)
        return False, {"ok": False, "error": str(e)}


# -------- webhook helpers --------
def set_webhook() -> Tuple[bool, Dict[str, Any]]:
    if not _cfg or not _base:
        return False, {"ok": False, "error": "not-initialized"}
    if not _cfg.PUBLIC_URL:
        return False, {"ok": False, "error": "PUBLIC_URL is empty"}

    url = f"{_cfg.PUBLIC_URL}/telegram"
    payload = {
        "url": url,
        "secret_token": _cfg.TELEGRAM_SECRET_TOKEN or "",
        # "allowed_updates": ["message", "edited_message", "callback_query"],
    }
    return _post_json(_api_url("setWebhook"), payload)


def get_webhook() -> Tuple[bool, Dict[str, Any]]:
    if not _base:
        return False, {"ok": False, "error": "not-initialized"}
    return _get_json(_api_url("getWebhookInfo"))


def del_webhook() -> Tuple[bool, Dict[str, Any]]:
    if not _base:
        return False, {"ok": False, "error": "not-initialized"}
    return _post_json(_api_url("deleteWebhook"), {"drop_pending_updates": True})


# -------- commands --------
def _cmd_help() -> str:
    return (
        "<b>Commands</b>\\n"
        "/help — this help\\n"
        "/status — price/EMA/RSI/MACD/ATR\\n"
        "/chart — chart close+EMA20\\n"
        "/train — run trainer (if exists)\\n"
        "/errors — last log lines\\n"
        "/setwebhook | /getwebhook | /delwebhook"
    )


def _status_text() -> str:
    if not (_cfg and _exchange):
        return "❗️ Not initialized."
    try:
        feats = aggregate_features(
            exchange=_exchange,
            symbol=_cfg.SYMBOL,
            timeframe=_cfg.TIMEFRAME,
            limit=_cfg.AGGREGATOR_LIMIT,
            settings=_cfg,
        )
        price = feats.get("last_close") or feats.get("price") or "-"
        rsi = feats.get("rsi")
        macd = feats.get("macd")
        macd_sig = feats.get("macd_signal") or feats.get("macd_signal_line")
        atrp = feats.get("atr_percent")
        ema20 = feats.get("ema20")
        dir_hint = "🟢" if (macd and macd_sig and macd > macd_sig) else ("🔴" if (macd and macd_sig and macd < macd_sig) else "⚪️")
        return (
            f"<b>{_cfg.SYMBOL}</b> {_cfg.TIMEFRAME} {dir_hint}\\n"
            f"Price: <b>{price}</b>\\n"
            f"EMA20: {ema20}\\n"
            f"RSI: {rsi}\\n"
            f"MACD: {macd} / {macd_sig}\\n"
            f"ATR%: {atrp}"
        )
    except Exception as e:
        logger.exception("status failed: %s", e)
        return f"⚠️ status error: {e}"


def _plot_chart_png(limit: int = 150) -> bytes:
    if not (_cfg and _exchange):
        raise RuntimeError("Not initialized")
    candles = _exchange.fetch_ohlcv(_cfg.SYMBOL, _cfg.TIMEFRAME, limit=limit)
    if not candles:
        raise RuntimeError("No OHLCV")

    df = pd.DataFrame(candles, columns=["ts","open","high","low","close","vol"])
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

    fig = plt.figure(figsize=(7, 3.2), dpi=140)
    ax = fig.add_subplot(111)
    ax.plot(df["close"].values, label="Close")
    ax.plot(df["ema20"].values, label="EMA20")
    ax.legend(loc="upper left")
    ax.set_title(f"{_cfg.SYMBOL} {_cfg.TIMEFRAME}")
    ax.grid(True, alpha=0.3)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _tail_log_lines(n: int = 60) -> str:
    try:
        import os
        path = getattr(_cfg, "LOG_FILE", None) if _cfg else None
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-n:]
            return "<code>" + "".join(lines)[-4090:] + "</code>"
    except Exception:
        pass
    return "No log file available."


# -------- dispatcher --------
def process_update(update: Dict[str, Any]) -> None:
    """Handle Telegram update dict (message only for simplicity)."""
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id") or _chat_id
        text = (msg.get("text") or "").strip()

        if text.startswith("/"):
            cmd = text.split()[0].lower()

            if cmd == "/help":
                tg_send_message(_cmd_help(), chat_id=chat_id); return

            if cmd == "/status":
                tg_send_message(_status_text(), chat_id=chat_id); return

            if cmd == "/chart":
                try:
                    png = _plot_chart_png()
                    tg_send_photo(png, caption="Chart", chat_id=chat_id)
                except Exception as e:
                    tg_send_message(f"⚠️ chart error: {e}", chat_id=chat_id)
                return

            if cmd == "/train":
                try:
                    from crypto_ai_bot.ml import trainer  # optional
                    trainer.run_training(_cfg)  # type: ignore
                    tg_send_message("✅ Training started.", chat_id=chat_id)
                except Exception:
                    tg_send_message("ℹ️ Trainer not available.", chat_id=chat_id)
                return

            if cmd == "/errors":
                tg_send_message(_tail_log_lines(), chat_id=chat_id); return

            if cmd == "/setwebhook":
                ok, resp = set_webhook()
                tg_send_message(f"setWebhook → ok={ok} resp={resp}", chat_id=chat_id); return

            if cmd == "/getwebhook":
                ok, resp = get_webhook()
                tg_send_message(f"getWebhook → ok={ok} resp={resp}", chat_id=chat_id); return

            if cmd == "/delwebhook":
                ok, resp = del_webhook()
                tg_send_message(f"deleteWebhook → ok={ok} resp={resp}", chat_id=chat_id); return

        # fallback
        if text:
            tg_send_message("Type /help", chat_id=chat_id)

    except Exception as e:
        logger.exception("process_update failed: %s", e)
'@
git add $path
git commit -m "telegram: clean bot adapter (no os.getenv, unified http client/indicators, commands & webhook)"
