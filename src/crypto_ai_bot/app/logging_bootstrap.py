from __future__ import annotations

import logging


def setup_telegram_error_handler() -> None:
    """
    Setup Telegram error handler if LOG_TG_ERRORS=1.
    Attaches to root logger but respects current formatter configuration.
    """
    try:
        from crypto_ai_bot.core.infrastructure.events.telegram_log_handler import TelegramErrorHandler

        handler = TelegramErrorHandler()
    except (ImportError, RuntimeError, ValueError) as exc:
        logging.getLogger(__name__).warning("TG error handler disabled: %s", exc)
        return

    handler.setLevel(logging.ERROR)
    fmt = logging.Formatter(fmt="🔴 %(levelname)s | %(name)s | %(message)s\nat %(pathname)s:%(lineno)d")
    handler.setFormatter(fmt)
    logging.getLogger().addHandler(handler)
