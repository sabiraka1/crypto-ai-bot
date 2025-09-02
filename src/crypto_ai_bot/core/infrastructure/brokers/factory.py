from __future__ import annotations

from typing import Any

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("brokers.factory")


def _import_first(*candidates: str) -> Any:  # Исправлено: добавлен return type
    """Import first available module from the list."""
    last_exc: Exception | None = None
    for path in candidates:
        try:
            module = __import__(path, fromlist=["*"])
            _log.info("broker_impl_found", extra={"module": path})
            return module
        except Exception as exc:  # try next candidate
            last_exc = exc
            continue
    # If nothing found — raise clear error
    raise ImportError(f"Broker implementation not found among: {', '.join(candidates)}") from last_exc


def _lower(value: Any, default: str = "") -> str:
    """Safely convert value to lowercase string."""
    try:
        s = (value or "").strip()
    except Exception:
        s = str(value or "")
    return s.lower() if isinstance(s, str) else default


def make_broker(*, exchange: str, mode: str, settings: Any) -> Any:
    """
    Фабрика брокеров:
      - MODE=paper -> PaperBroker
      - MODE=live  -> CcxtBroker (обёртка над CCXT)
    Никакого чтения ENV — только из объекта settings.
    """

    md = _lower(mode)
    ex = _lower(exchange, "gateio")  # по умолчанию gateio

    if md in ("paper", "sim", "simulation"):
        # Ищем класс симулятора в одном из известных мест
        mod = _import_first(
            "crypto_ai_bot.core.infrastructure.brokers.paper",
            "crypto_ai_bot.core.infrastructure.brokers.paper_broker",
            "crypto_ai_bot.core.infrastructure.brokers.simulator",
        )
        PaperBroker = getattr(mod, "PaperBroker", None)
        if PaperBroker is None:
            raise ImportError("PaperBroker class not found in paper broker module(s)")
        _log.info("make_broker_paper", extra={"exchange": ex})
        # PaperBroker обычно не требует ключей; передадим settings для общих параметров (таймауты и т.п.)
        return PaperBroker(settings=settings)

    if md in ("live", "real", "prod", "production"):
        # Ищем реализацию CCXT-брокера-обёртки в существующем файле ccxt_adapter
        mod = _import_first(
            "crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter",  # Исправлено - реальный файл
            "crypto_ai_bot.core.infrastructure.brokers.live",  # Запасной вариант
        )
        CcxtBroker = getattr(mod, "CcxtBroker", None)
        if CcxtBroker is None:
            raise ImportError("CcxtBroker class not found in ccxt broker module(s)")

        # Достаём ключи/таймауты из settings (settings уже сам позаботится о *_FILE / *_B64 если надо)
        api_key = getattr(settings, "API_KEY", "") or ""
        api_secret = getattr(settings, "API_SECRET", "") or ""
        api_password = getattr(settings, "API_PASSWORD", "") or ""  # для бирж, где требуется
        http_timeout_sec = float(getattr(settings, "HTTP_TIMEOUT_SEC", 30) or 30)
        proxy = getattr(settings, "HTTP_PROXY", "") or None  # если используется прокси

        # Для CcxtBroker нужен exchange объект из ccxt
        import ccxt
        exchange_class = getattr(ccxt, ex, None)
        if not exchange_class:
            raise ValueError(f"Exchange {ex} not found in ccxt")
        
        exchange_instance = exchange_class({
            'apiKey': api_key,
            'secret': api_secret,
            'password': api_password if api_password else None,
            'timeout': http_timeout_sec * 1000,  # ccxt использует миллисекунды
            'enableRateLimit': True,
            'proxies': proxy,
        })

        _log.info("make_broker_live", extra={"exchange": ex})
        return CcxtBroker(
            exchange=exchange_instance,
            settings=settings,
        )

    # Неизвестный режим — это ошибка конфигурации
    raise ValueError(f"Unsupported MODE={mode!r}. Use 'paper' or 'live'.")