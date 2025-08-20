# src/crypto_ai_bot/utils/idempotency.py
from __future__ import annotations

import binascii
from typing import Optional

# ВАЖНО: никаких импортов из core/*, чтобы не ломать слои
from crypto_ai_bot.utils.time import now_ms as _now_ms  # единая точка времени


__all__ = [
    "bucketize_ms",
    "normalize_symbol_for_key",
    "build_key",
    "validate_key",
    "crc_hint",
]


def bucketize_ms(ts_ms: int, bucket_ms: int) -> int:
    """
    Округляет отметку времени вниз до границы бакета.
    Пример: ts=169999, bucket=60000 -> 120000
    """
    if bucket_ms <= 0:
        raise ValueError("bucket_ms must be positive")
    return (ts_ms // bucket_ms) * bucket_ms


def normalize_symbol_for_key(symbol: str) -> str:
    """
    Нормализация торгового символа специально для ИДЕМПОТЕНТНЫХ КЛЮЧЕЙ.
    Не используем биржевую нормализацию (никаких core.brokers.*).
    Сделаем стабильный, человекочитаемый вид: 'BTC-USDT'
      - убираем пробелы
      - заменяем '/', '_' на '-'
      - приводим к верхнему регистру
    """
    s = (symbol or "").strip()
    s = s.replace("/", "-").replace("_", "-")
    s = "-".join(filter(None, s.split("-")))  # от двойных дефисов
    return s.upper()


def build_key(
    *,
    symbol: str,
    side: str,                 # "buy" | "sell"
    bucket_ms: int,
    decision_id: Optional[str] = None,
    ts_ms: Optional[int] = None,
) -> str:
    """
    Формирует единый идемпотентный ключ.
    Формат: "order:{SYMBOL}:{SIDE}:{BUCKET_MS}" [+":{DECISION}"]
    Решение: side приводим к нижнему регистру, symbol — через normalize_symbol_for_key().
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"invalid side: {side}")

    ts = ts_ms if ts_ms is not None else _now_ms()
    bucket = bucketize_ms(ts, bucket_ms)
    norm = normalize_symbol_for_key(symbol)
    base = f"order:{norm}:{side.lower()}:{bucket}"
    return f"{base}:{decision_id}" if decision_id else base


def validate_key(key: str) -> bool:
    """
    Простая валидация ключа идемпотентности.
    Требования:
      - str
      - длина 1..128
      - обязательно содержит хотя бы один ':'
    """
    return isinstance(key, str) and 1 <= len(key) <= 128 and (":" in key)


def crc_hint(s: str) -> str:
    """
    Короткая подсказка (8 hex) на основе CRC32. Удобно для clientOrderId-хинтов,
    если где-то надо уместить короткую подпись ключа (НЕ для криптографии).
    """
    v = binascii.crc32(s.encode("utf-8")) & 0xFFFFFFFF
    return f"{v:08x}"
