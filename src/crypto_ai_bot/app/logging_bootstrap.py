from __future__ import annotations

import logging

from crypto_ai_bot.core.infrastructure.events.telegram_log_handler import (
    TelegramErrorHandler,
)


def setup_telegram_error_handler() -> None:
    """
    РџРѕРґРєР»СЋС‡РёС‚СЊ РѕС‚РїСЂР°РІРєСѓ РѕС€РёР±РѕРє РІ Telegram, РµСЃР»Рё LOG_TG_ERRORS=1.
    Р’РµС€Р°РµРј РЅР° root-Р»РѕРіРіРµСЂ, РЅРѕ СѓРІР°Р¶Р°РµРј С‚РµРєСѓС‰СѓСЋ РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ С„РѕСЂРјР°С‚С‚РµСЂРѕРІ.
    """
    try:
        handler = TelegramErrorHandler()
    except Exception as exc:  # РєРѕРіРґР° РЅРµС‚ С‚РѕРєРµРЅР° РёР»Рё httpx РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ
        logging.getLogger(__name__).warning("TG error handler disabled: %s", exc)
        return  # noqa: TRY300

    handler.setLevel(logging.ERROR)
    fmt = logging.Formatter(fmt="рџ”ґ %(levelname)s | %(name)s | %(message)s\nat %(pathname)s:%(lineno)d")
    handler.setFormatter(fmt)
    logging.getLogger().addHandler(handler)
