from __future__ import annotations

from typing import Any

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("brokers.factory")


def _import_first(*candidates: str) -> Any:
    """Импортировать первый доступный модуль из списка."""
    last_exc: Exception | None = None
    for path in candidates:
        try:
            module = __import__(path, fromlist=["*"])
            _log.info("broker_impl_found", extra={"broker_module": path})
            return module
        except Exception as exc:
            last_exc = exc
            continue
    raise ImportError(f"Broker implementation not found among: {', '.join(candidates)}") from last_exc


def _lower(value: Any, default: str = "") -> str:
    """Безопасно привести значение к нижнему регистру (строка)."""
    try:
        s = (value or "").strip()
    except Exception:
        s = str(value or "")
    return s.lower() if isinstance(s, str) else default


def make_broker(*, exchange: str, mode: str, settings: Any) -> Any:
    """
    Фабрика брокеров:
      - MODE=paper -> PaperBroker (через порт-адаптер)
      - MODE=live  -> CcxtBroker (обёртка над CCXT)
    """
    md = _lower(mode)
    ex = _lower(exchange, "gateio")

    if md in ("paper", "sim", "simulation"):
        mod = _import_first("crypto_ai_bot.core.infrastructure.brokers.paper")
        PaperBroker = getattr(mod, "PaperBroker", None)
        PaperBrokerPortAdapter = getattr(mod, "PaperBrokerPortAdapter", None)
        if PaperBroker is None or PaperBrokerPortAdapter is None:
            raise ImportError("Paper broker or its port adapter not found in module")

        _log.info("make_broker_paper", extra={"exchange": ex})
        core = mod.PaperBroker(settings=settings)
        return mod.PaperBrokerPortAdapter(core)

    if md in ("live", "real", "prod", "production"):
        ccxt_mod = _import_first("crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter")
        CcxtBroker = getattr(ccxt_mod, "CcxtBroker", None)
        if CcxtBroker is None:
            raise ImportError("CcxtBroker class not found in ccxt broker module(s)")

        import ccxt  # локальный импорт

        if not hasattr(ccxt, ex):
            raise ValueError(f"Unsupported exchange {exchange!r} for ccxt")

        api_key = getattr(settings, "API_KEY", "") or ""
        api_secret = getattr(settings, "API_SECRET", "") or ""
        api_password = getattr(settings, "API_PASSWORD", "") or ""
        http_timeout_sec = float(getattr(settings, "HTTP_TIMEOUT_SEC", 30) or 30)
        proxy = getattr(settings, "HTTP_PROXY", "") or None

        cls = getattr(ccxt, ex)
        exch = cls(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "password": api_password or None,
                "timeout": int(http_timeout_sec * 1000),
                "enableRateLimit": True,
                **({"proxy": proxy} if proxy else {}),
            }
        )

        _log.info("make_broker_live", extra={"exchange": ex})
        return CcxtBroker(exchange=exch, settings=settings)

    raise ValueError(f"Unsupported MODE={mode!r}. Use 'paper' or 'live'.")
