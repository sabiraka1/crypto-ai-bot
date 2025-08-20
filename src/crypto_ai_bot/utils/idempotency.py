# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations

import re

_ALLOWED = re.compile(r"^[A-Za-z0-9:_\-/\.]+$")  # строгий набор для безопасных ключей
_MAX_LEN = 128

def validate_key(key: str) -> bool:
    """Проверка ключа идемпотентности: допустимые символы и разумная длина."""
    if not key or len(key) > _MAX_LEN:
        return False
    return bool(_ALLOWED.match(key))
