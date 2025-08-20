# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations

from typing import Callable, Optional


def quantize_bucket_ms(ts_ms: int, bucket_ms: int) -> int:
    """
    Округляет метку времени вниз до размерa бакета (миллисекунды).
    Пример: ts=1724147254321, bucket=60000 -> 1724147220000
    """
    if bucket_ms <= 0:
        return ts_ms
    return (ts_ms // bucket_ms) * bucket_ms


def _default_symbol_norm(s: str) -> str:
    """
    На случай если нормализатор не передан извне:
    приводим к верхнему регистру и унифицируем разделители.
    """
    return s.upper().replace("/", "-").replace("_", "-")


def make_order_key(
    *,
    raw_symbol: str,
    side: str,  # "buy" | "sell"
    bucket_ms: int,
    exchange: Optional[str] = None,
    normalizer: Optional[Callable[[str], str]] = None,
) -> str:
    """
    Строит идемпотентный ключ заявки. Никаких импортов из core!

    Формат:
      order:{exchange}:{symbol}:{side}:{bucket_ms}
    где exchange опционален (если не передан, опускается),
    symbol нормализуется переданным normalizer или дефолтно.
    """
    sym = normalizer(raw_symbol) if callable(normalizer) else _default_symbol_norm(raw_symbol)
    parts = ["order"]
    if exchange:
        parts.append(str(exchange).lower())
    parts.extend([sym, side, str(bucket_ms)])
    return ":".join(parts)
