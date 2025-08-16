# src/crypto_ai_bot/core/brokers/symbols.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ExchangeName = Literal["binance", "bybit", "okx", "paper", "backtest", "other"]

# ----------------------------- ВРЕМЕННЫЕ РАМКИ ------------------------------

# Канонический набор таймфреймов проекта
ALLOWED_TF: set[str] = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h",
    "1d", "3d",
    "1w",
    "1M",  # календарный месяц
}

# Алиасы → канон
_TF_ALIASES: dict[str, str] = {
    # минуты
    "1": "1m", "1min": "1m", "60s": "1m",
    "3": "3m", "3min": "3m",
    "5": "5m", "5min": "5m",
    "15": "15m", "15min": "15m",
    "30": "30m", "30min": "30m",
    # часы
    "60": "1h", "1h": "1h", "1hr": "1h", "1hour": "1h",
    "120": "2h", "2h": "2h",
    "240": "4h", "4h": "4h",
    "360": "6h", "6h": "6h",
    "720": "12h", "12h": "12h",
    # дни
    "1440": "1d", "1d": "1d", "1day": "1d",
    "3d": "3d",
    # недели
    "1w": "1w", "10080": "1w",
    # месяцы
    "1mo": "1M", "1mth": "1M", "1mon": "1M", "1month": "1M",
}

_TF_RE = re.compile(r"^\s*(\d+)\s*([mhdwM]?)\s*$", re.IGNORECASE)


def normalize_timeframe(tf: str) -> str:
    """
    Нормализует строку таймфрейма к канону проекта (ALLOWED_TF).
    Примеры: "15" → "15m"; "60" → "1h"; "1H" → "1h"; "1mo" → "1M".
    """
    if not tf:
        raise ValueError("timeframe is empty")
    s = tf.strip()
    low = s.lower()

    # прямой алиас
    if low in _TF_ALIASES:
        canon = _TF_ALIASES[low]
        if canon not in ALLOWED_TF:
            raise ValueError(f"timeframe alias to unsupported value: {canon}")
        return canon

    # шаблон вида "<число><единица?>"
    m = _TF_RE.match(s)
    if m:
        num, unit = m.groups()
        unit = unit or "m"  # по умолчанию минуты
        unit = unit.lower()

        if unit == "m":
            # числа минут: 60 → 1h; 240 → 4h; 1440 → 1d; 10080 → 1w
            minutes = int(num)
            if minutes == 60:
                return "1h"
            if minutes == 120:
                return "2h"
            if minutes == 240:
                return "4h"
            if minutes == 360:
                return "6h"
            if minutes == 720:
                return "12h"
            if minutes == 1440:
                return "1d"
            if minutes == 10080:
                return "1w"
            canon = f"{minutes}m"
        elif unit == "h":
            canon = f"{int(num)}h"
        elif unit == "d":
            if int(num) == 3:
                return "3d"
            if int(num) == 1:
                return "1d"
            raise ValueError(f"unsupported day timeframe: {s!r}")
        elif unit == "w":
            if int(num) == 1:
                return "1w"
            raise ValueError(f"unsupported week timeframe: {s!r}")
        elif unit == "m":  # уже обработано как минуты
            canon = f"{int(num)}m"
        elif unit == "M":
            if int(num) == 1:
                return "1M"
            raise ValueError(f"unsupported month timeframe: {s!r}")
        else:
            raise ValueError(f"unknown timeframe unit: {unit!r}")

        if canon not in ALLOWED_TF:
            raise ValueError(f"unsupported timeframe: {canon}")
        return canon

    # последнее: прямой канон?
    if s in ALLOWED_TF:
        return s

    raise ValueError(f"cannot normalize timeframe: {tf!r}")


# ------------------------------- СИМВОЛЫ -------------------------------------

# Кандидаты квот (суффикс) для разрезания слитных тикеров "BTCUSDT"
_COMMON_QUOTES = (
    "USDT", "USD", "USDC", "BUSD",
    "BTC", "ETH",
    "TRY", "EUR", "GBP", "JPY", "AUD"
)

# валидный токен: A-Z0-9 с дефисом и точкой (например, PERP/Вetа-формы)
_TICK_RE = re.compile(r"^[A-Z0-9][A-Z0-9\.-]{0,19}$")  # до 20 символов на токен
_SEP_RE = re.compile(r"[:\-\._]+")  # разделители → '/'

@dataclass(frozen=True)
class SymbolParts:
    base: str
    quote: str


def _split_solid_pair(s: str) -> SymbolParts | None:
    """
    Пытается разрезать слитный символ вида 'BTCUSDT' по известным квотам.
    Берёт максимальное совпадение квоты по хвосту.
    """
    up = s.upper()
    for q in sorted(_COMMON_QUOTES, key=len, reverse=True):
        if up.endswith(q) and len(up) > len(q):
            base = up[: len(up) - len(q)]
            return SymbolParts(base=base, quote=q)
    return None


def _sanitize_token(tok: str) -> str:
    tok = tok.upper().strip()
    if not _TICK_RE.match(tok):
        # убираем всё лишнее и повторяем проверку
        tok = re.sub(r"[^A-Z0-9\.-]", "", tok)
        if not tok or not _TICK_RE.match(tok):
            raise ValueError(f"invalid token: {tok!r}")
    return tok


def split_symbol(symbol: str) -> SymbolParts:
    """
    Делит каноническую строку символа на base/quote.
    Принимает широкие варианты: 'btc_usdt', 'BTCUSDT', 'BTC/USDT', 'BTC-USDT', 'ETHUSD:USD'.
    Возвращает base/quote в UPPERCASE; разделитель канона проекта — '/'.
    """
    if not symbol:
        raise ValueError("symbol is empty")

    raw = symbol.strip().upper()
    # отрезаем фьючерсные суффиксы ':USDT' / ':USD' (bybit/okx)
    raw = re.sub(r":(USDT|USD)$", "", raw)

    # заменяем любые разделители на '/'
    normalized = _SEP_RE.sub("/", raw)

    if "/" in normalized:
        base, quote = normalized.split("/", 1)
        base = _sanitize_token(base)
        quote = _sanitize_token(quote)
        return SymbolParts(base=base, quote=quote)

    # слитный вид 'BTCUSDT'
    parts = _split_solid_pair(normalized)
    if parts:
        return SymbolParts(base=_sanitize_token(parts.base), quote=_sanitize_token(parts.quote))

    raise ValueError(f"cannot parse symbol: {symbol!r}")


def join_symbol(base: str, quote: str) -> str:
    """Склеивает канонический символ base/quote с разделителем '/'."""
    return f"{_sanitize_token(base)}/{_sanitize_token(quote)}"


def normalize_symbol(symbol: str) -> str:
    """
    Нормализует произвольную запись к канону проекта 'BASE/QUOTE' (UPPERCASE).
    Не добавляет фьючерсные постфиксы.
    """
    parts = split_symbol(symbol)
    return join_symbol(parts.base, parts.quote)


def to_exchange_symbol(exchange: ExchangeName, symbol: str, *, contract: Literal["spot", "linear", "inverse"] | None = None) -> str:
    """
    Преобразует канонический символ к виду конкретной биржи/контракта (для ccxt).
    - spot: 'BTC/USDT'
    - bybit linear/okx/usdt-margined futures: 'BTC/USDT:USDT'
    - inverse (USD-margined): 'BTC/USD:USD'
    """
    base, quote = split_symbol(symbol).base, split_symbol(symbol).quote
    if exchange in ("paper", "backtest", "other"):
        return f"{base}/{quote}"

    ex = exchange.lower()
    if contract is None or contract == "spot":
        return f"{base}/{quote}"

    if contract == "linear":
        # usdt-margined perp: требуется ':USDT' на некоторых биржах (bybit/okx)
        if ex in ("bybit", "okx"):
            return f"{base}/{quote}:{quote}"
        return f"{base}/{quote}"

    if contract == "inverse":
        # usd-margined perp: ':USD'
        if ex in ("bybit", "okx"):
            if quote != "USD":
