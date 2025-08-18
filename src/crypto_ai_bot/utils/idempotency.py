# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations
import re
import time
from typing import Literal

from crypto_ai_bot.core.brokers.symbols import normalize_symbol

# Единый формат: source:BASE-QUOTE:side:epoch_ms_bucket_start
# Примеры: "order:BTC-USDT:buy:1723987200000", "eval:ETH-USDT:sell:1723987200000"
_KEY_RE = re.compile(r"^(order|eval):[A-Z0-9\-]+:(buy|sell):\d{13}$")

def build_key(
    *,
    symbol: str,
    side: Literal["buy", "sell"],
    bucket_ms: int,
    source: Literal["order", "eval"] = "order",
) -> str:
    """
    Генерация ключа идемпотентности.
    - symbol нормализуется (BASE/QUOTE -> BASE-QUOTE в верхнем регистре)
    - time bucket округляется вниз к началу "ведра"
    """
    sym_u = normalize_symbol(symbol).upper().replace("/", "-")
    now_ms = int(time.time() * 1000)
    b = int(max(1, bucket_ms))
    bucket_start = (now_ms // b) * b
    return f"{source}:{sym_u}:{side}:{bucket_start}"

def validate_key(key: str) -> bool:
    """Проверка, что ключ соответствует формату."""
    return bool(_KEY_RE.match(key))
