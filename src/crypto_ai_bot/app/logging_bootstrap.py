from __future__ import annotations

import logging


def setup_telegram_error_handler() -> None:
    """
    Подключает TelegramErrorHandler при LOG_TG_ERRORS=1.
    - Добавляет хендлер к root-логгеру.
    - Не трогает существующие форматтеры/уровни, не делает дублей.
    """
    try:
        # Исправлен путь импорта на актуальный
        from crypto_ai_bot.app.telegram_log_handler import TelegramErrorHandler  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning("TG error handler disabled (import): %s", exc)
        return

    # Инициализация хендлера может бросить, если ENV не полон — ловим это внутри.
    try:
        handler = TelegramErrorHandler()
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning("TG error handler disabled (init): %s", exc)
        return

    handler.setLevel(logging.ERROR)

    # Аккуратный текстовый формат для Telegram (оставляем эмодзи и краткую привязку к месту)
    fmt = logging.Formatter(fmt="🔴 %(levelname)s | %(name)s | %(message)s\nat %(pathname)s:%(lineno)d")
    handler.setFormatter(fmt)

    root = logging.getLogger()
    # не добавляем дубль
    for h in root.handlers:
        if type(h) is type(handler):  # noqa: E721 — намеренное сравнение типов
            return

    root.addHandler(handler)
