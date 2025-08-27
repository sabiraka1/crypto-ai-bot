## `core/validators/settings.py`
from __future__ import annotations
from typing import List
from crypto_ai_bot.utils.exceptions import ValidationError
ALLOWED_MODES = {"paper", "live", "backtest"}
ALLOWED_EXCHANGES = {"gateio"}
def validate_settings(settings) -> List[str]:
    """Return list of human-readable errors. Empty list means valid.
    Do NOT read os.environ here; validate a ready Settings object.
    """
    errors: List[str] = []
    mode = getattr(settings, "MODE", None)
    if mode not in ALLOWED_MODES:
        errors.append(f"MODE must be one of {sorted(ALLOWED_MODES)}, got: {mode!r}")
    exch = getattr(settings, "EXCHANGE", None)
    if exch not in ALLOWED_EXCHANGES:
        errors.append(f"Unsupported EXCHANGE: {exch!r}. Allowed: {sorted(ALLOWED_EXCHANGES)}")
    symbol = getattr(settings, "SYMBOL", "")
    if not isinstance(symbol, str) or not symbol:
        errors.append("SYMBOL must be a non-empty string like 'BTC/USDT'")
    elif "/" not in symbol:
        errors.append("SYMBOL must contain '/' (e.g., 'BTC/USDT')")
    fixed_amount = getattr(settings, "FIXED_AMOUNT", None)
    try:
        if fixed_amount is None or float(fixed_amount) <= 0:  # decimal-safe check
            errors.append("FIXED_AMOUNT must be > 0")
    except Exception:
        errors.append("FIXED_AMOUNT must be a number > 0")
    ttl_sec = getattr(settings, "IDEMPOTENCY_TTL_SEC", 0)
    bucket_ms = getattr(settings, "IDEMPOTENCY_BUCKET_MS", 0)
    if not isinstance(ttl_sec, int) or ttl_sec <= 0:
        errors.append("IDEMPOTENCY_TTL_SEC must be positive integer")
    if not isinstance(bucket_ms, int) or bucket_ms <= 0:
        errors.append("IDEMPOTENCY_BUCKET_MS must be positive integer (milliseconds)")
    db_path = getattr(settings, "DB_PATH", "")
    if not isinstance(db_path, str) or not db_path.strip():
        errors.append("DB_PATH must be a non-empty file path for SQLite")
    tg_enabled = bool(getattr(settings, "TELEGRAM_ENABLED", False))
    if tg_enabled:
        tok = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat = getattr(settings, "TELEGRAM_CHAT_ID", "")
        if not tok:
            errors.append("TELEGRAM_ENABLED=true requires TELEGRAM_BOT_TOKEN to be set")
        if not chat:
            errors.append("TELEGRAM_ENABLED=true requires TELEGRAM_CHAT_ID to be set")
    if mode == "live":
        api_key = getattr(settings, "API_KEY", "")
        api_secret = getattr(settings, "API_SECRET", "")
        if not api_key or not api_secret:
            errors.append("MODE=live requires API_KEY and API_SECRET")
    port = getattr(settings, "SERVER_PORT", 0)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        errors.append("SERVER_PORT must be integer in [1, 65535]")
    return errors
