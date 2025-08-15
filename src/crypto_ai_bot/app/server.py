
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# --- Imports that may vary across trees ----------------------------------
try:
    # unified config (new path)
    from crypto_ai_bot.core.settings import Settings
except Exception:  # fallback to legacy path if needed
    from crypto_ai_bot.core.settings import Settings  # type: ignore

# get_bot factory
try:
    from crypto_ai_bot.core.bot import get_bot  # type: ignore
except Exception:
    from crypto_ai_bot.trading.bot import get_bot  # type: ignore

# exchange client (optional)
try:
    from crypto_ai_bot.trading.exchange_client import ExchangeClient  # type: ignore
except Exception:
    ExchangeClient = None  # type: ignore

# unified telegram adapter (we keep it optional)
try:
    from crypto_ai_bot.telegram.handler import tg_send_message, process_update  # type: ignore
except Exception:
    tg_send_message = None  # type: ignore

    async def process_update(_: Dict[str, Any]) -> None:  # type: ignore
        return None

logger = logging.getLogger("crypto_ai_bot.app.server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s:%(name)s:%(message)s")

app = FastAPI(title="crypto-ai-bot")

_settings: Optional[Settings] = None
_exchange: Optional[Any] = None
_bot: Optional[Any] = None


# ----------------------------- helpers -----------------------------------
def _unified_notifier(text: str) -> None:
    """Send text to Telegram (if adapter & token configured). Best-effort."""
    try:
        if tg_send_message is None:
            return
        tg_send_message(text)
    except Exception as e:  # nosec
        logger.debug("Notifier failed: %s", e)

def _safe_start_bot(bot: Any) -> None:
    """Start trading loop if the bot exposes a suitable method.
    We support several common names and never raise.
    """
    try:
        for attr in ("start", "start_loop", "start_background", "run_background"):
            if hasattr(bot, attr):
                getattr(bot, attr)()
                logger.info("Bot started via %s()", attr)
                return
        # As a last resort, spawn a thread around `run` if it exists and is blocking
        if hasattr(bot, "run"):
            import threading
            t = threading.Thread(target=getattr(bot, "run"), name="TradingLoop", daemon=True)
            t.start()
            logger.info("Bot started in background thread via run()")
    except Exception as e:  # nosec
        logger.warning("Could not auto-start bot: %s", e)

def _try_set_webhook(base_url: str, token: str, secret: Optional[str]) -> Dict[str, Any]:
    try:
        import requests  # lazy import
    except Exception:
        return {"ok": False, "error": "requests_not_installed"}

    url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {"url": f"{base_url.rstrip('/')}/telegram"}
    if secret:
        payload["secret_token"] = secret
    try:
        r = requests.post(url, json=payload, timeout=10)
        return {"ok": True, "result": r.json()}
    except Exception as e:  # nosec
        return {"ok": False, "error": str(e)}


# ----------------------------- lifecycle ---------------------------------
@app.on_event("startup")
def on_startup() -> None:
    global _settings, _exchange, _bot
    cfg = Settings.build()
    _settings = cfg
    logger.info("Startup with SYMBOL=%s TIMEFRAME=%s", cfg.SYMBOL, cfg.TIMEFRAME)

    # Exchange (optional)
    if ExchangeClient is not None:
        try:
            _exchange = ExchangeClient(
                api_key=cfg.API_KEY or cfg.GATE_API_KEY,
                api_secret=cfg.API_SECRET or cfg.GATE_API_SECRET,
                paper=bool(cfg.PAPER_MODE),
                symbol=cfg.SYMBOL,
                timeframe=cfg.TIMEFRAME,
            )
        except Exception as e:  # nosec
            logger.warning("Exchange init failed — %s", e)
            _exchange = None
    else:
        _exchange = None

    # Bot (always best-effort)
    try:
        _bot = get_bot(exchange=_exchange, notifier=_unified_notifier, settings=cfg)
        _safe_start_bot(_bot)
    except Exception as e:  # nosec
        logger.error("Trading bot init failed — %s", e)

    # Webhook (best-effort)
    if cfg.PUBLIC_URL and cfg.TELEGRAM_BOT_TOKEN:
        res = _try_set_webhook(cfg.PUBLIC_URL, cfg.TELEGRAM_BOT_TOKEN, getattr(cfg, "TELEGRAM_SECRET_TOKEN", None))
        logger.info("setWebhook(%s/telegram) → %s", cfg.PUBLIC_URL, res)

# ------------------------------- routes -----------------------------------
@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True, "have_bot": bool(_bot), "symbol": getattr(_settings, "SYMBOL", None)}

@app.get("/metrics")
def metrics() -> Response:
    # minimal metrics without prometheus_client
    lines = [
        "# HELP app_up 1 if app is up",
        "# TYPE app_up gauge",
        "app_up 1",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain")

@app.get("/config")
def config() -> Dict[str, Any]:
    if not _settings:
        return {"ok": False, "error": "no_settings"}
    data = {k: getattr(_settings, k) for k in dir(_settings) if k.isupper()}
    # hide secrets
    for k in ("API_KEY", "API_SECRET", "GATE_API_KEY", "GATE_API_SECRET", "TELEGRAM_BOT_TOKEN"):
        if k in data and data[k]:
            data[k] = "***"
    return {"ok": True, "config": data}

@app.post("/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    cfg = _settings or Settings.build()
    # optional secret check
    wanted = getattr(cfg, "TELEGRAM_SECRET_TOKEN", None)
    if wanted:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not got or got != wanted:
            return JSONResponse({"ok": False, "error": "bad_secret"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=400)

    try:
        await process_update(payload)  # safe proxy to telegram.bot.process_update
        return JSONResponse({"ok": True})
    except Exception as e:  # nosec
        logger.error("process_update failed: %s", e)
        return JSONResponse({"ok": False, "error": "process_failed"}, status_code=500)

# default info endpoint
@app.get("/")
def root() -> Dict[str, Any]:
    return {"name": "crypto-ai-bot", "status": "ok"}

