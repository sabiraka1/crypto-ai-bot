import logging

from crypto_ai_bot.core.infrastructure.events.telegram_log_handler import (
    TelegramErrorHandler,
)


def setup_telegram_error_handler() -> None:
    """
    Подключить отправку ошибок в Telegram, если LOG_TG_ERRORS=1.
    Вешаем на root-логгер, но уважаем текущую конфигурацию форматтеров.
    """
    try:
        handler = TelegramErrorHandler()
    except Exception as exc:  # когда нет токена или httpx не установлен
        logging.getLogger(__name__).warning("TG error handler disabled: %s", exc)
        return

    handler.setLevel(logging.ERROR)
    fmt = logging.Formatter(
        fmt="🔴 %(levelname)s | %(name)s | %(message)s\n"
            "at %(pathname)s:%(lineno)d"
    )
    handler.setFormatter(fmt)
    logging.getLogger().addHandler(handler)
