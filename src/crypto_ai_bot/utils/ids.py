from __future__ import annotations
import time
import uuid
import hashlib


def _normalize_symbol(symbol: str) -> str:
    """Нормализует символ к формату AAA-BBB (например, BTC/USDT → BTC-USDT)."""
    return symbol.replace("/", "-").upper()


def make_idempotency_key(symbol: str, side: str, bucket_ms: int, *, now_ms: int | None = None) -> str:
    """Формат строго: {symbol}:{side}:{bucket_start_ms}.
    Пример: "BTC-USDT:buy:1699920000000". bucket_ms — размер окна (мс).
    """
    ts = int(now_ms if now_ms is not None else time.time() * 1000)
    bucket_start = (ts // bucket_ms) * bucket_ms
    return f"{_normalize_symbol(symbol)}:{side.lower()}:{bucket_start}"


def make_correlation_id() -> str:
    """Корреляционный ID (trace) для сквозного трейсинга."""
    return str(uuid.uuid4())


def make_client_order_id(exchange: str, key: str, *, max_len: int = 32) -> str:
    """Генерирует clientOrderId под биржу. Для Gate.io формат: "t-{hash}-{ts}".
    Допускаются символы [0-9A-Za-z._-]; при переполнении — сокращение и добавление хеша.
    """
    prefix = "t-" if exchange.lower() in {"gate", "gateio", "gate.io"} else ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    sanitized = "".join(ch for ch in key if ch in allowed) or "0"
    ts = str(int(time.time() * 1000))
    h = hashlib.sha256(sanitized.encode()).hexdigest()[:8]
    base = f"{prefix}{h}-{ts}"
    return base[:max_len]