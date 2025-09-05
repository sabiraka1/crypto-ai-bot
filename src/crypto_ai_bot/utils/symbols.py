from __future__ import annotations

from typing import Iterable, Optional, Tuple

# Часто встречающиеся котируемые активы (UPPERCASE)
_COMMON_QUOTES: set[str] = {
    "USDT", "USDC", "BUSD", "USD", "EUR", "TRY",
    "BTC", "ETH", "BNB", "FDUSD", "DAI",
}

# Предвычислим котируемые активы, отсортированные по длине (длинные сначала),
# чтобы корректно распознавать, например, FDUSD vs USD
_QUOTES_SORTED: tuple[str, ...] = tuple(sorted(_COMMON_QUOTES, key=len, reverse=True))

# Алиасы активов (UPPERCASE)
_ALIASES: dict[str, str] = {"XBT": "BTC", "XETH": "ETH", "BCC": "BCH"}

# Разделители, встречающиеся на биржах
_SEPARATORS: tuple[str, ...] = ("/", "-", "_", ":")


def _clean(s: str) -> str:
    """Очищает и нормализует строку тикера: trim + upper + оставляет только [A-Z0-9] и разделители."""
    return "".join(ch for ch in (s or "").strip().upper() if ch.isalnum() or ch in _SEPARATORS)


def _apply_alias(asset: str) -> str:
    """Применяет алиас к активу (если есть)."""
    return _ALIASES.get(asset, asset)


def _try_split_by_separator(s: str) -> Optional[Tuple[str, str]]:
    """
    Пытается разбить символ по известным разделителям так, чтобы правая часть
    была известной котируемой валютой. Если удаётся — возвращает (base, quote).
    """
    for sep in _SEPARATORS:
        if sep not in s:
            continue
        parts = [p for p in s.split(sep) if p != ""]
        if len(parts) < 2:
            continue

        # Идём слева направо: выбираем такую позицию, где справа стоит котируемая валюта.
        for j in range(1, len(parts)):
            q = _apply_alias(parts[j])
            if q in _COMMON_QUOTES:
                left = sep.join(parts[:j])

                # Если слева строка оканчивается на котируемую валюту (частый случай BTCUSDT-…),
                # отбросим этот суффикс, чтобы получить чистый base.
                base = left[:-len(q)] if left.endswith(q) else left
                return _apply_alias(base), q
    return None


def split(symbol: str) -> tuple[str, str]:
    """
    Возвращает (base, quote). Если распарсить невозможно — возвращает (asset, "").
    Стратегия:
      1) пробуем разделители и выбираем сплит, где справа — котируемая валюта;
      2) если разделителей нет или не помогло, ищем котируемую валюту как суффикс.
    """
    s = _clean(symbol)
    if not s:
        return "", ""

    # 1) Разбор по разделителям (умный)
    by_sep = _try_split_by_separator(s)
    if by_sep is not None:
        return by_sep

    # 2) Без разделителей: ищем известную котируемую валюту как суффикс
    for q in _QUOTES_SORTED:
        if s.endswith(q) and len(s) > len(q):
            base = s[: -len(q)]
            return _apply_alias(base), _apply_alias(q)

    # Ничего не нашли — считаем строку названием актива без котируемой
    return _apply_alias(s), ""


def canonical(symbol: str) -> str:
    """Возвращает каноническое представление BASE/QUOTE или просто BASE, если QUOTE не найден."""
    base, quote = split(symbol)
    return f"{base}/{quote}" if base and quote else base


def is_valid(symbol: str) -> bool:
    """
    Валиден ли тикер: есть base и quote, оба состоят из [A-Z0-9], и они не равны.
    (После _clean() разделители удаляются сплитом; строгая проверка на alnum оставлена намеренно.)
    """
    base, quote = split(symbol)
    return bool(base and quote and base.isalnum() and quote.isalnum() and base != quote)
