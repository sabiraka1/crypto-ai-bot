# src/crypto_ai_bot/utils/idempotency.py
"""
Idempotency helpers:
- Строго локальные утилиты, без импортов из core/*
- Построение ключей, валидация, бакетизация по времени
"""

from __future__ import annotations
from typing import Dict, Optional
import re
import time
import zlib

# Разрешённые символы и длина для безопасного ключа (под хранение/индексы)
_SAFE_KEY_RE = re.compile(r"^[a-z0-9:/._\-]{1,128}$")

def now_ms() -> int:
    return int(time.time() * 1000)

def validate_key(key: str) -> bool:
    """Проверка допустимости ключа для БД/логов/метрик."""
    return bool(_SAFE_KEY_RE.match(key))

def bucketize_ms(ts_ms: int, bucket_ms: int) -> int:
    """Привязка таймстемпа к «корзине» (например, минутной)."""
    if bucket_ms <= 0:
        return ts_ms
    return (ts_ms // bucket_ms) * bucket_ms

def _normalize_symbol_for_key(symbol: str) -> str:
    """
    Локальная нормализация: BTC/USDT | btc_usdt | btc-usdt -> BTC-USDT.
    Без зависимости от core.brokers.symbols.
    """
    s = symbol.strip().replace("_", "-").replace("/", "-").upper()
    s = re.sub(r"[^A-Z0-9\-]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

def build_key(
    *,
    kind: str,
    symbol: str,
    side: Optional[str] = None,
    bucket_ms: Optional[int] = None,
    extra: Optional[Dict[str, str]] = None,
    ts_ms: Optional[int] = None,
) -> str:
    """
    Конструирует стабильный идемпотентный ключ.
    Пример: "order:BTC-USDT:buy:1734712800000:dec=f1"
    """
    ts = ts_ms if ts_ms is not None else now_ms()
    norm_sym = _normalize_symbol_for_key(symbol)
    parts = [kind.lower(), norm_sym]
    if side:
        parts.append(side.lower())
    if bucket_ms:
        parts.append(str(bucketize_ms(ts, bucket_ms)))
    if extra:
        for k, v in sorted(extra.items()):
            # короткий хвост (crc32) для доп. стабильности без длинных строк
            crc = zlib.crc32(f"{k}={v}".encode("utf-8")) & 0xFFFFFFFF
            parts.append(f"{k[:6]}={crc:08x}")
    key = ":".join(parts).lower()
    # safety net
    if not validate_key(key):
        # отрежем экзотику / длинные места
        key = re.sub(r"[^a-z0-9:/._\-]", "-", key)[:128].strip(":-")
    return key
