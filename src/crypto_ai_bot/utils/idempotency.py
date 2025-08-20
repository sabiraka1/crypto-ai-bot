# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations

import re
import zlib
from typing import Final


# Разрешённая форма ключа (достаточно строгая, без привязки к core.*)
_KEY_RE: Final = re.compile(r"^[a-z0-9:\-_/]{6,200}$")


def build_key(*parts: str) -> str:
    """
    Построение ключа вида "order:BTC-USDT:buy:1734721200".
    Составляющие нормализуем в нижний регистр и склеиваем ":".
    """
    norm = [str(p).strip().lower() for p in parts if p and str(p).strip()]
    return ":".join(norm)


def validate_key(key: str) -> bool:
    """
    Лёгкая валидация формата ключа без зависимости от core.*.
    Репозиторий может вызвать перед insert — удобно ловить мусор заранее.
    """
    if not key:
        return False
    if len(key) > 200:
        return False
    return bool(_KEY_RE.match(key))


def crc32_of(text: str) -> str:
    """CRC32 от строки в hex для компактных client-side ID."""
    return f"{zlib.crc32(text.encode('utf-8')) & 0xffffffff:08x}"
