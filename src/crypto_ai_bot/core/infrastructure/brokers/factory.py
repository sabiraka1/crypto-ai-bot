from __future__ import annotations

from typing import Any

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("brokers.factory")


def _import_first(*candidates: str) -> Any:
    """Import first available module from the list."""
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
    """Safely convert value to lowercase string."""
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
        mod = _import_first(
            "crypto_ai_bot.core.infrastructure.brokers.paper",
            # "crypto_ai_bot.core.infrastructure.brokers.simulator",  # удалён тобой — оставим как комментарий
        )
        # Берём PaperBroker и его порт-адаптер
        PaperBroker = getattr(mod, "PaperBroker", None)
        PaperBrokerPortAdapter = getattr(mod, "PaperBrokerPortAdapter", None)
        if PaperBroker is None or PaperBrokerPortAdapter is None:
            raise ImportError("Paper broker or its port adapter not found in module")

        _log.info("make_broker_paper", extra={"exchange": ex})
        # ВНИМАНИЕ: сохраняем текущую сигнатуру — PaperBroker(settings=...)
        core = PaperBroker(settings=settings)
        return PaperBrokerPortAdapter(core)

    if md in ("live", "real", "prod", "production"):
        mod = _import_first(
            "crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter",
            "crypto_ai_bot.core.infrastructure.brokers.live",
        )
        CcxtBroker = getattr(mod, "CcxtBroker", None)
        if CcxtBroker is None:
            raise ImportError("CcxtBroker class not found in ccxt broker module(s)")

        api_key = getattr(settings, "API_KEY", "") or ""
        api_secret = getattr(settings, "API_SECRET", "") or ""
        api_password = getattr(settings, "API_PASSWORD", "") or ""
        http_timeout_sec = float(getattr(settings, "HTTP_TIMEOUT_SEC", 30) or 30)
        proxy = getattr(settings, "HTTP_PROXY", "") or None

        _log.info("make_broker_live", extra={"exchange": ex})
        return CcxtBroker(
            exchange=ex,
            api_key=api_key,
            api_secret=api_secret,
            api_password=api_password if api_password else None,
            timeout_sec=http_timeout_sec,
            proxy=proxy,
            settings=settings,
        )

    raise ValueError(f"Unsupported MODE={mode!r}. Use 'paper' or 'live'.")
